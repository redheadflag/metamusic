import json
import math
import os
import shutil
import tempfile

from .audio import download_track, embed_metadata, fetch_cover_art
from .metadata import (
    parse_sc_metadata,
    apply_sc_overrides,
    display_metadata,
    _normalize,
)
from .utils import log, die, run, safe_name

SC_SEARCH_RESULTS = 10  # results per scsearch query
YTDLP_CONFIG = os.environ.get("YTDLP_CONFIG", "/app/config/yt-dlp.conf")


def _ytdlp_base() -> list[str]:
    cmd = ["yt-dlp"]
    if os.path.exists(YTDLP_CONFIG):
        cmd += ["--config-location", YTDLP_CONFIG]
        log(f"Using yt-dlp config: {YTDLP_CONFIG}")
    return cmd


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


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


def find_best_sc_track(
    album_artist: str, track_title: str, target_duration: int
) -> dict:
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


def fetch_full_sc_track_info(track: dict) -> dict:
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


# ---------------------------------------------------------------------------
# Fetch playlist / single track entries
# ---------------------------------------------------------------------------


def fetch_sc_entries(sc_url: str) -> list[dict]:
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
        die(f"yt-dlp returned no entries for SoundCloud URL.\n{result.stderr}")

    log(f"Found {len(entries)} SC entry/entries.")
    return entries


# ---------------------------------------------------------------------------
# Process one SC entry end-to-end
# ---------------------------------------------------------------------------


def process_sc_entry(
    raw: dict,
    MUSIC_LIBRARY_PATH: str,
    track_number: int | None = None,
    overrides: dict | None = None,
) -> None:
    """Parse SC metadata, apply overrides, display, download, tag, and save."""
    meta = parse_sc_metadata(raw, track_number=track_number)
    if overrides:
        meta = apply_sc_overrides(meta, overrides)
    cover_art = fetch_cover_art(raw)

    display_metadata(meta)

    out_dir = os.path.join(
        MUSIC_LIBRARY_PATH, safe_name(meta["album_artist"]), safe_name(meta["album"])
    )
    os.makedirs(out_dir, exist_ok=True)
    safe_file_name = safe_name(f"{meta['artist']} — {meta['track']}") + ".mp3"
    final_path = os.path.join(out_dir, safe_file_name)

    sc_track = {"webpage_url": raw.get("webpage_url") or raw.get("url")}
    with tempfile.TemporaryDirectory() as tmpdir:
        mp3_path = download_track(sc_track, tmpdir)
        embed_metadata(mp3_path, meta, cover_art)
        shutil.move(mp3_path, final_path)

    log(f"Saved: {final_path}")
