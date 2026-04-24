"""
Fetch a YouTube playlist's track list using yt-dlp --dump-single-json.
No authentication required for public playlists; YouTube Music playlists
may need a cookie file set via YOUTUBE_COOKIES_FILE.
"""

import json
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
        return ["--cookies", cookies]
    return []


def fetch_playlist(url: str) -> dict:
    """
    Fetch a YouTube playlist and return:
      { playlist_id, playlist_name, tracks: [{video_id, title, artist, duration, thumbnail}] }
    """
    cmd = [
        _ytdlp(),
        "--dump-single-json",
        "--flat-playlist",
        "--quiet",
        *_cookies_args(),
        url,
    ]

    logger.info("Fetching YouTube playlist: %s", url)
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("yt-dlp timed out while fetching playlist")

    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp failed: {result.stderr[-800:]}")

    if not result.stdout.strip():
        raise RuntimeError("yt-dlp returned no output — check the URL")

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Could not parse yt-dlp output: {exc}")

    playlist_id = data.get("id", "")
    playlist_name = data.get("title") or "YouTube Playlist"
    entries = data.get("entries") or []

    tracks = []
    for entry in entries:
        if not entry:
            continue

        video_id = entry.get("id", "")
        title = (entry.get("title") or "").strip()
        # uploader = channel name; prefer 'artist' tag if present (rare in flat output)
        artist = (
            entry.get("artist")
            or entry.get("uploader")
            or entry.get("channel")
            or ""
        ).strip()
        duration = entry.get("duration")
        thumbnail = entry.get("thumbnail") or None

        if not video_id or not title:
            continue

        tracks.append({
            "video_id": video_id,
            "title": title,
            "artist": artist,
            "duration": int(duration) if duration else None,
            "thumbnail": thumbnail,
        })

    logger.info(
        "Playlist %r: %d track(s) found", playlist_name, len(tracks)
    )
    return {
        "playlist_id": playlist_id,
        "playlist_name": playlist_name,
        "tracks": tracks,
    }


def fetch_video(url: str) -> dict:
    """
    Fetch metadata for a single YouTube video without downloading.
    Returns: {video_id, title, artist, duration, thumbnail}
    """
    cmd = [
        _ytdlp(),
        "--dump-single-json",
        "--skip-download",
        "--no-playlist",
        "--quiet",
        *_cookies_args(),
        url,
    ]

    logger.info("Fetching YouTube video metadata: %s", url)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        raise RuntimeError("yt-dlp timed out while fetching video")

    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp failed: {result.stderr[-800:]}")

    if not result.stdout.strip():
        raise RuntimeError("yt-dlp returned no output — check the URL")

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Could not parse yt-dlp output: {exc}")

    video_id = data.get("id", "")
    if not video_id:
        raise RuntimeError("Could not determine video ID from URL")

    title = (data.get("title") or "").strip()
    artist = (
        data.get("artist")
        or data.get("uploader")
        or data.get("channel")
        or ""
    ).strip()
    duration = data.get("duration")
    thumbnail = data.get("thumbnail") or None

    return {
        "video_id": video_id,
        "title": title,
        "artist": artist,
        "duration": int(duration) if duration else None,
        "thumbnail": thumbnail,
    }
