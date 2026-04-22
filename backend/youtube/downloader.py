"""
Download a single YouTube video as MP3 using yt-dlp.

Intentionally does NOT use the shared config/yt-dlp.conf because that file
is tuned for SoundCloud (wrong Referer header, SC cookies, rate-limiting for SC
API patterns).  YouTube downloads use a minimal command with a separate
cookie file if YOUTUBE_COOKIES_FILE is set.
"""

import logging
import os
import shutil
import subprocess

logger = logging.getLogger(__name__)

YOUTUBE_COOKIES_FILE = os.environ.get("YOUTUBE_COOKIES_FILE", "").strip()


def _ytdlp() -> str:
    b = shutil.which("yt-dlp")
    if not b:
        raise FileNotFoundError("yt-dlp not found in PATH")
    return b


def _cookies_args() -> list[str]:
    cookies = YOUTUBE_COOKIES_FILE
    if cookies and os.path.exists(cookies):
        logger.info("Using YouTube cookies: %s", cookies)
        return ["--cookies", cookies]
    return []


def download_youtube_track(video_id: str, dest_dir: str) -> str:
    """
    Download a YouTube video as MP3 into dest_dir.
    The file is named <video_id>.mp3 to avoid any title-based naming issues.
    Returns the absolute path to the downloaded .mp3 file.
    Raises RuntimeError on failure.
    """
    yt_url = f"https://www.youtube.com/watch?v={video_id}"
    output_tmpl = os.path.join(dest_dir, "%(id)s.%(ext)s")

    cmd = [
        _ytdlp(),
        "--extract-audio",
        "--audio-format", "mp3",
        "--audio-quality", "0",
        "--embed-metadata",
        "--embed-thumbnail",
        "--output", output_tmpl,
        "--no-playlist",
        "--quiet",
        *_cookies_args(),
        yt_url,
    ]

    logger.info("Downloading YouTube video: %s", video_id)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

    if result.returncode != 0:
        raise RuntimeError(
            f"yt-dlp failed for {video_id} (exit {result.returncode}):\n"
            f"{result.stderr[-600:]}"
        )

    # Locate the produced .mp3 file (named <video_id>.mp3)
    expected = os.path.join(dest_dir, f"{video_id}.mp3")
    if os.path.exists(expected):
        return expected

    # Fallback: find any .mp3 in dest_dir
    for fname in os.listdir(dest_dir):
        if fname.endswith(".mp3"):
            return os.path.join(dest_dir, fname)

    raise RuntimeError(f"yt-dlp produced no MP3 for {video_id}")


def retag_mp3(path: str, title: str, artists, album: str) -> None:
    """
    Update the ID3 text tags in an MP3 file without touching the existing
    APIC (cover art) frame embedded by yt-dlp.
    Keeps all other frames (APIC, etc.) intact — only overwrites TIT2/TPE1/
    TPE2/TALB/TRCK/TDRC.

    *artists* may be a string (split on common separators) or a list of
    strings.  Written as a multi-value TPE1/TPE2 frame in ID3v2.4.
    """
    try:
        from mutagen.id3 import ID3, ID3NoHeaderError, TALB, TDRC, TIT2, TPE1, TPE2, TRCK
    except ImportError:
        logger.warning("mutagen not installed — skipping tag override for %s", path)
        return

    if isinstance(artists, str):
        from fix_artists import split_artist

        parts = split_artist(artists) or ([artists.strip()] if artists.strip() else [])
    else:
        parts = [str(a).strip() for a in (artists or []) if str(a).strip()]

    try:
        try:
            tags = ID3(path)
        except ID3NoHeaderError:
            tags = ID3()

        tags["TIT2"] = TIT2(encoding=3, text=title)
        tags["TPE1"] = TPE1(encoding=3, text=parts)
        tags["TPE2"] = TPE2(encoding=3, text=parts)
        tags["TALB"] = TALB(encoding=3, text=album)
        tags["TDRC"] = TDRC(encoding=3, text="")
        tags["TRCK"] = TRCK(encoding=3, text="1")
        tags.save(path, v2_version=4)
    except Exception as exc:
        logger.warning("retag_mp3 failed for %s: %s", path, exc)


def fix_track(path: str) -> None:
    """Sanitize M4A streams for a single file. Non-fatal."""
    from fix_artists import sanitize_m4a_streams

    try:
        sanitize_m4a_streams(path)
    except Exception as exc:
        logger.warning("sanitize_m4a_streams failed for %s (non-fatal): %s", path, exc)
