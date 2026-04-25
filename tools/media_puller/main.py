# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "httpx>=0.27",
#   "mutagen>=1.47",
#   "paramiko>=3.4",
#   "Pillow>=10",
#   "yt-dlp>=2024.11",
# ]
# ///

"""
tools/media_puller/main.py
──────────────────────────
Local worker: claims pending download jobs (YouTube + SoundCloud) from the
VPS queue, downloads each track, uploads via SFTP, and reports done/failed.

Config — .env file in the same directory as this script:
    API_BASE              https://myserver.com/api
    PULLER_TOKEN          shared secret matching YT_PULLER_TOKEN on the server
    SFTP_HOST             remote hostname
    SFTP_PORT             (optional, default 22)
    SFTP_USER             login username
    SFTP_KEY_FILE         path to private key (preferred over password)
    SFTP_PASSWORD         password (fallback)
    SFTP_BASE             absolute path on remote, e.g. /home/user/music
    YOUTUBE_COOKIES_FILE  (optional) yt-dlp cookies file for YouTube
    SC_COOKIES_FILE       (optional) yt-dlp cookies file for SoundCloud
    CLAIM_LIMIT           jobs per poll cycle (default 3)
    POLL_INTERVAL         seconds between polls when idle (default 30)
"""

from __future__ import annotations

import base64
import logging
import os
import re
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from io import BytesIO
from pathlib import Path, PurePosixPath

import httpx
import paramiko
from mutagen.id3 import APIC, ID3, ID3NoHeaderError, TALB, TDRC, TIT2, TPE1, TPE2, TRCK
from PIL import Image

logger = logging.getLogger(__name__)


# ── config ────────────────────────────────────────────────────────────────────

def _load_env() -> None:
    """Load .env from the same directory as this script into os.environ."""
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val


_load_env()

API_BASE = os.environ.get("API_BASE", "").rstrip("/")
PULLER_TOKEN = os.environ.get("PULLER_TOKEN", "")
SFTP_HOST = os.environ.get("SFTP_HOST", "")
SFTP_PORT = int(os.environ.get("SFTP_PORT", "22"))
SFTP_USER = os.environ.get("SFTP_USER", "")
SFTP_BASE = os.environ.get("SFTP_BASE", "").rstrip("/")
SFTP_KEY_FILE: str | None = os.environ.get("SFTP_KEY_FILE") or None
SFTP_PASSWORD: str | None = os.environ.get("SFTP_PASSWORD") or None
YOUTUBE_COOKIES_FILE = os.environ.get("YOUTUBE_COOKIES_FILE", "").strip()
SC_COOKIES_FILE = os.environ.get("SC_COOKIES_FILE", "").strip()
WORKER_ID = socket.gethostname()
CLAIM_LIMIT = int(os.environ.get("CLAIM_LIMIT", "3"))
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "30"))


# ── filename sanitizer ────────────────────────────────────────────────────────

def _safe(s: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "_", s).strip()


# ── artwork ───────────────────────────────────────────────────────────────────

def _crop_to_square(img_data: bytes) -> bytes:
    """Center-crop a landscape image to square. Returns original bytes if already square/portrait."""
    with Image.open(BytesIO(img_data)) as img:
        w, h = img.size
        if w <= h:
            return img_data
        left = (w - h) // 2
        img = img.crop((left, 0, left + h, h))
        buf = BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=95)
        return buf.getvalue()


def _embed_cover(path: str, img_data: bytes) -> None:
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()
    tags.delall("APIC")
    tags["APIC"] = APIC(encoding=0, mime="image/jpeg", type=3, desc="Cover", data=img_data)
    tags.save(path, v2_version=4)


def _crop_embedded_cover(path: str) -> None:
    """Extract embedded cover, square-crop it, and re-embed."""
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        return
    apic_keys = [k for k in tags if k.startswith("APIC")]
    if not apic_keys:
        return
    apic = tags[apic_keys[0]]
    cropped = _crop_to_square(apic.data)
    if cropped is apic.data:
        return
    _embed_cover(path, cropped)


# ── SFTP ──────────────────────────────────────────────────────────────────────

class _SFTPClient:
    def __init__(self) -> None:
        self._ssh: paramiko.SSHClient | None = None
        self._sftp: paramiko.SFTPClient | None = None
        self._lock = threading.Lock()

    def _connect(self) -> None:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(
            hostname=SFTP_HOST,
            port=SFTP_PORT,
            username=SFTP_USER,
            key_filename=SFTP_KEY_FILE,
            password=SFTP_PASSWORD,
            timeout=15,
        )
        self._ssh = ssh
        self._sftp = ssh.open_sftp()
        logger.info("SFTP connected to %s", SFTP_HOST)

    def _ensure(self) -> paramiko.SFTPClient:
        if self._sftp is None:
            self._connect()
            return self._sftp  # type: ignore[return-value]
        try:
            self._sftp.stat(SFTP_BASE)
        except (OSError, EOFError, paramiko.SSHException):
            logger.warning("SFTP connection lost — reconnecting…")
            self._close()
            self._connect()
        return self._sftp  # type: ignore[return-value]

    def _close(self) -> None:
        for obj in (self._sftp, self._ssh):
            try:
                if obj:
                    obj.close()
            except Exception:
                pass
        self._sftp = None
        self._ssh = None

    def _makedirs(self, sftp: paramiko.SFTPClient, remote_dir: str) -> None:
        parts = PurePosixPath(remote_dir).parts
        current = ""
        for part in parts:
            current = f"{current}/{part}" if current else part
            if current == "/":
                continue
            try:
                sftp.stat(current)
            except IOError:
                sftp.mkdir(current)

    def upload(self, local_path: str, remote_path: str) -> None:
        with self._lock:
            sftp = self._ensure()
            self._makedirs(sftp, str(PurePosixPath(remote_path).parent))
            sftp.put(local_path, remote_path)
            logger.info("Uploaded: %s → %s", local_path, remote_path)


_sftp_client = _SFTPClient()


# ── downloads ─────────────────────────────────────────────────────────────────

def _ytdlp_bin() -> str:
    b = shutil.which("yt-dlp")
    if not b:
        raise FileNotFoundError("yt-dlp not found in PATH")
    return b


def download_youtube_track(source_url: str, dest_dir: str) -> str:
    """Download a YouTube video as MP3. Returns absolute path to .mp3."""
    m = re.search(r"[?&]v=([^&]+)", source_url)
    video_id = m.group(1) if m else None
    output_tmpl = os.path.join(dest_dir, "%(id)s.%(ext)s")

    cookies_args: list[str] = []
    if YOUTUBE_COOKIES_FILE and os.path.exists(YOUTUBE_COOKIES_FILE):
        cookies_args = ["--cookies", YOUTUBE_COOKIES_FILE]

    cmd = [
        _ytdlp_bin(),
        "--extract-audio", "--audio-format", "mp3", "--audio-quality", "0",
        "--embed-metadata", "--embed-thumbnail",
        "--output", output_tmpl,
        "--no-playlist", "--quiet",
        *cookies_args,
        source_url,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(
            f"yt-dlp failed for {source_url} (exit {result.returncode}):\n"
            f"{result.stderr[-600:]}"
        )

    if video_id:
        expected = os.path.join(dest_dir, f"{video_id}.mp3")
        if os.path.exists(expected):
            return expected
    for fname in os.listdir(dest_dir):
        if fname.endswith(".mp3"):
            return os.path.join(dest_dir, fname)
    raise RuntimeError(f"yt-dlp produced no MP3 for {source_url}")


def download_soundcloud_track(sc_url: str, dest_dir: str) -> str:
    """Download a SoundCloud track as MP3 via yt-dlp. Returns absolute path to .mp3."""
    output_tmpl = os.path.join(dest_dir, "%(title)s.%(ext)s")

    cookies_args: list[str] = []
    if SC_COOKIES_FILE and os.path.exists(SC_COOKIES_FILE):
        cookies_args = ["--cookies", SC_COOKIES_FILE]

    cmd = [
        _ytdlp_bin(),
        "--extract-audio", "--audio-format", "mp3", "--audio-quality", "0",
        "--embed-metadata", "--embed-thumbnail",
        "--output", output_tmpl,
        "--no-playlist", "--quiet",
        *cookies_args,
        sc_url,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(
            f"yt-dlp failed for {sc_url} (exit {result.returncode}):\n"
            f"{result.stderr[-600:]}"
        )

    for fname in os.listdir(dest_dir):
        if fname.endswith(".mp3"):
            return os.path.join(dest_dir, fname)
    raise RuntimeError(f"yt-dlp produced no MP3 for {sc_url}")


def retag_mp3(
    path: str,
    title: str,
    artists: list[str],
    album_artists: list[str] | None = None,
    album: str = "",
    release_year: str = "",
    track_number: int | None = None,
) -> None:
    """Overwrite ID3 text tags, keeping the embedded cover art intact."""
    parts = [str(a).strip() for a in (artists or []) if str(a).strip()]
    aa_parts = [str(a).strip() for a in (album_artists or parts) if str(a).strip()]
    try:
        try:
            tags = ID3(path)
        except ID3NoHeaderError:
            tags = ID3()
        tags.delall("TCON")
        tags.delall("COMM")
        tags["TIT2"] = TIT2(encoding=3, text=title)
        tags["TPE1"] = TPE1(encoding=3, text=parts)
        tags["TPE2"] = TPE2(encoding=3, text=aa_parts)
        tags["TALB"] = TALB(encoding=3, text=album)
        tags["TDRC"] = TDRC(encoding=3, text=release_year or "")
        tags["TRCK"] = TRCK(encoding=3, text=str(track_number) if track_number else "")
        tags.save(path, v2_version=4)
    except Exception as exc:
        logger.warning("retag_mp3 failed for %s: %s", path, exc)


# ── API helpers ───────────────────────────────────────────────────────────────

def _headers() -> dict:
    return {"X-Puller-Token": PULLER_TOKEN, "Content-Type": "application/json"}


def api_claim() -> list[dict]:
    r = httpx.post(
        f"{API_BASE}/queue/claim",
        json={"worker_id": WORKER_ID, "limit": CLAIM_LIMIT},
        headers=_headers(),
        timeout=15,
    )
    r.raise_for_status()
    return r.json()


def api_done(job_id: int, remote_path: str) -> None:
    r = httpx.post(
        f"{API_BASE}/queue/{job_id}/done",
        json={"remote_path": remote_path},
        headers=_headers(),
        timeout=60,
    )
    r.raise_for_status()


def api_failed(job_id: int, error: str) -> None:
    try:
        httpx.post(
            f"{API_BASE}/queue/{job_id}/failed",
            json={"error": error},
            headers=_headers(),
            timeout=15,
        )
    except Exception as exc:
        logger.warning("Could not report failure for job %d: %s", job_id, exc)


# ── job processing ────────────────────────────────────────────────────────────

def process_job(job: dict) -> str:
    """Download, tag, upload one job. Returns the remote SFTP path."""
    source: str = job.get("source", "youtube")
    source_url: str = (
        job.get("source_url")
        or f"https://www.youtube.com/watch?v={job['video_id']}"
    )
    download_mode: str = job.get("download_mode", "playlist")
    title: str = job["title"]
    artists: list[str] = job.get("artists") or []
    album_artists: list[str] = job.get("album_artists") or artists
    album: str = job.get("album") or title
    release_year: str = job.get("release_year") or ""
    cover_art_b64: str | None = job.get("cover_art_b64") or None
    thumbnail: str | None = job.get("thumbnail") or None
    track_number: int | None = job.get("track_number")

    folder = _safe(album_artists[0] if album_artists else (artists[0] if artists else "Unknown"))
    fname = _safe(title) + ".mp3"
    if album:
        remote = str(PurePosixPath(SFTP_BASE) / folder / _safe(album) / fname)
    else:
        remote = str(PurePosixPath(SFTP_BASE) / folder / fname)

    tmp_dir = tempfile.mkdtemp(prefix="media_puller_")
    try:
        # Download audio
        if source == "youtube":
            mp3_path = download_youtube_track(source_url, tmp_dir)
        elif source == "soundcloud":
            mp3_path = download_soundcloud_track(source_url, tmp_dir)
        else:
            raise ValueError(f"Unknown source: {source!r}")

        retag_mp3(
            mp3_path,
            title=title,
            artists=artists,
            album_artists=album_artists,
            album=album,
            release_year=release_year,
            track_number=track_number,
        )

        # Cover art handling
        if download_mode == "album":
            cover_b64 = job.get("album_cover_b64") or cover_art_b64
            if cover_b64:
                cover_bytes = _crop_to_square(base64.b64decode(cover_b64))
                _embed_cover(mp3_path, cover_bytes)
                # Upload cover.jpg once per album folder (idempotent — same bytes each time)
                album_dir = str(PurePosixPath(remote).parent)
                cover_remote = f"{album_dir}/cover.jpg"
                cover_tmp = os.path.join(tmp_dir, "cover.jpg")
                Path(cover_tmp).write_bytes(cover_bytes)
                _sftp_client.upload(cover_tmp, cover_remote)
            else:
                _crop_embedded_cover(mp3_path)
        else:
            # Playlist mode: per-track cover
            if cover_art_b64:
                raw = base64.b64decode(cover_art_b64)
                _embed_cover(mp3_path, _crop_to_square(raw))
            elif thumbnail:
                try:
                    resp = httpx.get(thumbnail, timeout=15, follow_redirects=True)
                    resp.raise_for_status()
                    _embed_cover(mp3_path, _crop_to_square(resp.content))
                except Exception as exc:
                    logger.warning("Could not fetch thumbnail %s: %s", thumbnail, exc)
                    _crop_embedded_cover(mp3_path)
            else:
                _crop_embedded_cover(mp3_path)

        _sftp_client.upload(mp3_path, remote)
        return remote
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ── main loop ─────────────────────────────────────────────────────────────────

def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    missing = [k for k, v in [("API_BASE", API_BASE), ("SFTP_HOST", SFTP_HOST)] if not v]
    if missing:
        raise SystemExit(f"Missing required config: {', '.join(missing)} — check .env")

    logger.info("media_puller started (worker=%s  api=%s)", WORKER_ID, API_BASE)

    while True:
        try:
            jobs = api_claim()
        except Exception as exc:
            logger.error("Claim failed: %s — retrying in %ds", exc, POLL_INTERVAL)
            time.sleep(POLL_INTERVAL)
            continue

        if not jobs:
            logger.debug("No pending jobs. Sleeping %ds.", POLL_INTERVAL)
            time.sleep(POLL_INTERVAL)
            continue

        for job in jobs:
            jid: int = job["id"]
            logger.info("[%d] Processing: %s (%s)", jid, job.get("title", "?"), job.get("source", "youtube"))
            try:
                remote = process_job(job)
                api_done(jid, remote)
                logger.info("[%d] Done → %s", jid, remote)
            except Exception as exc:
                logger.error("[%d] Failed: %s", jid, exc)
                api_failed(jid, str(exc))


def run_once() -> None:
    """Claim all pending jobs, process them, then exit."""
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    missing = [k for k, v in [("API_BASE", API_BASE), ("SFTP_HOST", SFTP_HOST)] if not v]
    if missing:
        raise SystemExit(f"Missing required config: {', '.join(missing)} — check .env")

    logger.info("media_puller (one-shot) started (worker=%s  api=%s)", WORKER_ID, API_BASE)

    total_claimed = 0
    failed = 0

    while True:
        try:
            jobs = api_claim()
        except Exception as exc:
            raise SystemExit(f"Claim failed: {exc}")

        if not jobs:
            break

        total_claimed += len(jobs)
        for job in jobs:
            jid: int = job["id"]
            logger.info("[%d] Processing: %s (%s)", jid, job.get("title", "?"), job.get("source", "youtube"))
            try:
                remote = process_job(job)
                api_done(jid, remote)
                logger.info("[%d] Done → %s", jid, remote)
            except Exception as exc:
                logger.error("[%d] Failed: %s", jid, exc)
                api_failed(jid, str(exc))
                failed += 1

    logger.info("Done. %d track(s) processed, %d failed.", total_claimed, failed)
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Media track downloader for metamusic")
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Run as a polling daemon (checks for new jobs every POLL_INTERVAL seconds)",
    )
    args = parser.parse_args()

    if args.daemon:
        run()
    else:
        run_once()
