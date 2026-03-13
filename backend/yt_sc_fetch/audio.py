import os
import re
import sys
import tempfile
import urllib.request

from .utils import log, die, run


# ---------------------------------------------------------------------------
# Cover art
# ---------------------------------------------------------------------------

def fetch_cover_art(track_info: dict) -> bytes | None:
    """Download the highest-quality cover art from a yt-dlp info dict."""
    artwork_url = track_info.get("thumbnail") or track_info.get("artwork_url")
    if not artwork_url:
        thumbnails = track_info.get("thumbnails") or []
        if thumbnails:
            best = max(
                thumbnails,
                key=lambda t: t.get("width") or t.get("preference") or 0,
            )
            artwork_url = best.get("url")

    if not artwork_url:
        log("No cover art URL found.")
        return None

    # Request the highest-quality SoundCloud variant
    artwork_url = re.sub(r"-(large|t500x500)\b", "-original", artwork_url)
    log(f"Fetching cover art: {artwork_url}")
    try:
        req = urllib.request.Request(artwork_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.read()
    except Exception as exc:
        log(f"Warning: could not fetch cover art – {exc}")
        return None


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def _track_url(track: dict) -> str:
    return (
        track.get("webpage_url")
        or track.get("url")
        or track.get("permalink_url")
        or ""
    )


def download_track(track: dict, MUSIC_LIBRARY_PATH: str) -> str:
    """
    Download a track (SC or any yt-dlp-supported source) as MP3.
    Returns the path to the produced .mp3 file.
    """
    url = _track_url(track)
    if not url:
        die("Could not determine a URL for the selected track.")

    log(f"Downloading: {url}")
    output_tmpl = os.path.join(MUSIC_LIBRARY_PATH, "%(id)s.%(ext)s")
    result = run([
        "yt-dlp",
        "--no-playlist",
        "--format",        "bestaudio/best",
        "--extract-audio",
        "--audio-format",  "mp3",
        "--audio-quality", "0",
        "--no-embed-metadata",
        "--no-embed-thumbnail",
        "--output",        output_tmpl,
        url,
    ])
    if result.returncode != 0:
        die(f"yt-dlp download failed:\n{result.stderr}")

    for fname in os.listdir(MUSIC_LIBRARY_PATH):
        if fname.endswith(".mp3"):
            return os.path.join(MUSIC_LIBRARY_PATH, fname)

    die("yt-dlp finished but no .mp3 file was produced.")


# ---------------------------------------------------------------------------
# Tag embedding
# ---------------------------------------------------------------------------

def embed_metadata(mp3_path: str, meta: dict, cover_art: bytes | None) -> None:
    """Write ID3v2.3 tags (and optional cover art) into an MP3 file."""
    try:
        from mutagen.id3 import (
            ID3, ID3NoHeaderError,
            TPE1, TPE2, TALB, TIT2, TDRC, TCON, TRCK, APIC,
        )
    except ImportError:
        die("mutagen is not installed.  Run: pip install mutagen")

    log(f"Embedding metadata into: {mp3_path}")
    try:
        tags = ID3(mp3_path)
    except ID3NoHeaderError:
        tags = ID3()

    tags.clear()
    tags.add(TPE1(encoding=3, text=meta["artist"]))
    tags.add(TPE2(encoding=3, text=meta["album_artist"]))
    tags.add(TALB(encoding=3, text=meta["album"]))
    tags.add(TIT2(encoding=3, text=meta["track"]))
    tags.add(TDRC(encoding=3, text=str(meta["release_year"])))

    if meta.get("track_number") is not None:
        tags.add(TRCK(encoding=3, text=str(meta["track_number"])))

    if meta.get("tags"):
        tags.add(TCON(encoding=3, text="; ".join(meta["tags"][:5])))

    if cover_art:
        mime = "image/png" if cover_art[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"
        tags.add(APIC(encoding=3, mime=mime, type=3, desc="Cover", data=cover_art))

    tags.save(mp3_path, v2_version=3)
    log("Metadata embedded.")
