"""
Raw audio download from SoundCloud via yt-dlp.

No FFmpeg post-processing — files are saved in their native format.
The external processor service is responsible for conversion and tagging.
"""

import json
import logging
import math
import os
import subprocess
import tempfile

from .utils import log, run

logger = logging.getLogger(__name__)

YTDLP_CONFIG = os.environ.get("YTDLP_CONFIG", "/app/config/yt-dlp.conf")
SC_SEARCH_RESULTS = 10


def _ytdlp_base() -> list[str]:
    cmd = ["yt-dlp"]
    if os.path.exists(YTDLP_CONFIG):
        cmd += ["--config-location", YTDLP_CONFIG]
        log(f"Using yt-dlp config: {YTDLP_CONFIG}")
    return cmd


def _count_audio_streams(path: str) -> int:
    """Return the number of audio streams in *path* via ffprobe."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-select_streams", "a",
                "-show_entries", "stream=index",
                "-of", "csv=p=0",
                path,
            ],
            capture_output=True,
            text=True,
        )
        lines = [l for l in result.stdout.splitlines() if l.strip()]
        logger.info("_count_audio_streams: %s → %d stream(s) (ffprobe stdout=%r stderr=%r)",
                    os.path.basename(path), len(lines), result.stdout[:200], result.stderr[:200])
        return len(lines)
    except FileNotFoundError:
        logger.warning("_count_audio_streams: ffprobe not found — skipping sanitization for %s",
                       os.path.basename(path))
        return 0


def sanitize_m4a_streams(path: str) -> str:
    """
    If *path* is an .m4a with more than one audio stream, rewrite it so that
    only the first audio stream (``-map 0:a:0``) is kept.  The file is
    replaced in-place; any tags/cover already in stream 0 are preserved
    because we use ``-c copy`` (no re-encoding).

    Returns the (unchanged) path so callers can use it in a chain.
    """
    if not path.lower().endswith(".m4a"):
        logger.info("sanitize_m4a_streams: skipping non-m4a file %s", os.path.basename(path))
        return path

    n_streams = _count_audio_streams(path)
    logger.info("sanitize_m4a_streams: %s has %d audio stream(s)", os.path.basename(path), n_streams)
    if n_streams <= 1:
        return path

    logger.info("sanitize_m4a_streams: stripping extra streams from %s", os.path.basename(path))

    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".m4a", dir=os.path.dirname(path))
    os.close(tmp_fd)
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", path,
                "-map", "0:a:0",
                "-map", "0:v?",
                "-c", "copy",
                tmp_path,
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logger.warning("sanitize_m4a_streams: ffmpeg failed for %s, keeping original.\nstderr: %s",
                           os.path.basename(path), result.stderr[-500:])
            os.unlink(tmp_path)
            return path

        os.replace(tmp_path, path)
        logger.info("sanitize_m4a_streams: OK — %s stripped to single audio stream", os.path.basename(path))
    except Exception as exc:
        logger.warning("sanitize_m4a_streams: error for %s (%s), keeping original",
                       os.path.basename(path), exc)
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    return path


def download_raw(sc_url: str, tmp_dir: str) -> str:
    """
    Download the best available audio for *sc_url* into *tmp_dir*.
    Returns the path of the produced file (native format, no conversion).

    For .m4a files with multiple audio streams (a common SoundCloud artefact),
    the file is sanitized in-place so that only the first audio stream survives.
    Cover art embedded in the container (stream 0:v) is preserved.
    Raises RuntimeError on failure.
    """
    output_tmpl = os.path.join(tmp_dir, "%(id)s.%(ext)s")
    result = run(_ytdlp_base() + [
        "--no-playlist",
        "--format", "bestaudio/best",
        "--no-embed-metadata", "--no-embed-thumbnail",
        "--output", output_tmpl,
        sc_url,
    ])
    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp failed: {result.stderr[-500:]}")
    files = os.listdir(tmp_dir)
    if not files:
        raise RuntimeError("yt-dlp produced no file")

    raw_file = os.path.join(tmp_dir, files[0])
    sanitize_m4a_streams(raw_file)   # no-op for non-m4a or single-stream files
    return raw_file


# ---------------------------------------------------------------------------
# Search helpers (used by CLI / batch flows)
# ---------------------------------------------------------------------------

def _normalize(s: str) -> str:
    """Lowercase and strip typographic quotes for fuzzy comparison."""
    return s.lower().translate(
        str.maketrans("\u2018\u2019\u201c\u201d\u02bc\u0060", "''\"\"\u0027\u0027")
    )


def _ytdlp_search(query: str, n: int = SC_SEARCH_RESULTS) -> list[dict]:
    search_url = f"scsearch{n}:{query}"
    log(f"  SC search: {search_url!r}")
    result = run(
        _ytdlp_base() + [
            "--dump-json",
            "--flat-playlist",
            "--no-playlist",
            search_url,
        ]
    )
    tracks = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            tracks.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return tracks


def find_best_track(album_artist: str, track_title: str, target_duration: int) -> dict:
    """
    Search SoundCloud and return the best-matching track dict, or {} on miss.

    Matching criteria:
      • title contains track_title (case-insensitive, punctuation-normalised)
      • duration within 5% of target_duration — waived when album_artist
        already appears in the SC title (could be a clip/edit)
    """
    duration_tolerance = math.ceil(target_duration * 0.05)
    queries = [f"{album_artist} {track_title}", track_title]
    needle = _normalize(track_title)
    artist_lower = _normalize(album_artist)

    for query in queries:
        log(f"Searching SoundCloud: '{query}'")
        results = _ytdlp_search(query)
        log(f"  {len(results)} result(s)")

        for t in results:
            title = _normalize(t.get("title") or "")
            dur = int(float(t.get("duration") or 0))
            title_ok = needle in title
            artist_in_title = artist_lower in title
            dur_ok = artist_in_title or abs(dur - target_duration) <= duration_tolerance

            log(
                f"  • '{t.get('title')}' | {dur}s "
                f"| title={title_ok} dur={dur_ok} artist_in_title={artist_in_title}"
            )

            if title_ok and dur_ok:
                log(f"  ✓ '{t.get('title')}' @ {t.get('url') or t.get('webpage_url')}")
                return t

    return {}


def fetch_entries(sc_url: str) -> list[dict]:
    """
    Return a list of raw yt-dlp info dicts from a SoundCloud URL.
    Works for single tracks, playlists, and albums.
    """
    log(f"Fetching SoundCloud entries for: {sc_url}")
    result = run(
        _ytdlp_base() + [
            "--dump-json",
            "--yes-playlist",
            "--skip-download",
            sc_url,
        ]
    )
    entries = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            pass

    if not entries:
        raise RuntimeError(f"yt-dlp returned no entries for SoundCloud URL.\n{result.stderr}")

    log(f"Found {len(entries)} SC entry/entries.")
    return entries


def fetch_full_track_info(track: dict) -> dict:
    """Re-fetch full metadata for a flat-playlist result (adds thumbnail, etc.)."""
    url = track.get("webpage_url") or track.get("url") or ""
    if not url:
        return track
    log(f"Fetching full SC track info: {url}")
    result = run(_ytdlp_base() + ["--dump-json", "--no-playlist", "--skip-download", url])
    if result.returncode != 0:
        return track
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return track
