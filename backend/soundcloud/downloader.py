"""
Raw audio download from SoundCloud via yt-dlp.

No FFmpeg post-processing — files are saved in their native format.
The external processor service is responsible for conversion and tagging.
"""

import json
import logging
import math
import os

from fix_artists import sanitize_m4a_streams

from .utils import log, run

logger = logging.getLogger(__name__)

YTDLP_CONFIG = os.environ.get("YTDLP_CONFIG", "/app/config/yt-dlp.conf")
# Explicit SoundCloud cookie file.  When set, overrides the --cookies path
# baked into yt-dlp.conf so the file can live anywhere on the host.
SC_COOKIES_FILE = os.environ.get("SC_COOKIES_FILE", "").strip()
SC_SEARCH_RESULTS = 10


def _ytdlp_base() -> list[str]:
    cmd = ["yt-dlp"]
    if os.path.exists(YTDLP_CONFIG):
        cmd += ["--config-location", YTDLP_CONFIG]
        log(f"Using yt-dlp config: {YTDLP_CONFIG}")
    if SC_COOKIES_FILE and os.path.exists(SC_COOKIES_FILE):
        # Override the cookies path from yt-dlp.conf (last --cookies wins)
        cmd += ["--cookies", SC_COOKIES_FILE]
        log(f"Using SC cookies override: {SC_COOKIES_FILE}")
    return cmd


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
    result = run(
        _ytdlp_base()
        + [
            "--no-playlist",
            "--format",
            "bestaudio/best",
            "--no-embed-metadata",
            "--no-embed-thumbnail",
            "--output",
            output_tmpl,
            sc_url,
        ]
    )
    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp failed: {result.stderr[-500:]}")
    files = os.listdir(tmp_dir)
    if not files:
        raise RuntimeError("yt-dlp produced no file")

    raw_file = os.path.join(tmp_dir, files[0])
    sanitize_m4a_streams(raw_file)  # no-op for non-m4a or single-stream files
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
        _ytdlp_base()
        + [
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
        _ytdlp_base()
        + [
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
        raise RuntimeError(
            f"yt-dlp returned no entries for SoundCloud URL.\n{result.stderr}"
        )

    log(f"Found {len(entries)} SC entry/entries.")
    return entries


def fetch_full_track_info(track: dict) -> dict:
    """Re-fetch full metadata for a flat-playlist result (adds thumbnail, etc.)."""
    url = track.get("webpage_url") or track.get("url") or ""
    if not url:
        return track
    log(f"Fetching full SC track info: {url}")
    result = run(
        _ytdlp_base() + ["--dump-json", "--no-playlist", "--skip-download", url]
    )
    if result.returncode != 0:
        return track
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return track
