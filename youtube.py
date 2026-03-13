import json
import os
import shutil
import tempfile

from .audio    import download_track, embed_metadata, fetch_cover_art
from .metadata import parse_yt_metadata
from .sc       import find_best_sc_track, fetch_full_sc_track_info
from .utils    import log, warn, die, run, safe_name


def fetch_yt_entries(url: str) -> list[dict]:
    """
    Return a list of raw yt-dlp info dicts for every entry in *url*.
    Works for single videos and playlists/albums.
    """
    log(f"Fetching YouTube entries for: {url}")
    result = run([
        "yt-dlp",
        "--dump-json",
        "--yes-playlist",
        "--skip-download",
        url,
    ])
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
        die(f"yt-dlp returned no entries for the given URL.\n{result.stderr}")

    log(f"Found {len(entries)} entry/entries.")
    return entries


def process_yt_entry(raw: dict, output_dir: str,
                     track_number: int | None = None) -> str | None:
    """
    Process one YouTube entry end-to-end.
    Returns None on success, or a label string if the SC match was not found.
    """
    meta  = parse_yt_metadata(raw, track_number=track_number)
    log(f"\n── Track: {meta['artist']} – {meta['track']} ({meta['duration']}s)")

    sc_track = find_best_sc_track(meta["album_artist"], meta["track"], meta["duration"])
    if not sc_track:
        label = f"{meta['artist']} – {meta['track']}"
        warn(f"Skipping '{label}': no matching SoundCloud track found.")
        return label

    sc_track_full = fetch_full_sc_track_info(sc_track)
    cover_art     = fetch_cover_art(sc_track_full)

    out_dir = os.path.join(
        output_dir, safe_name(meta["album_artist"]), safe_name(meta["album"])
    )
    os.makedirs(out_dir, exist_ok=True)
    safe_file_name = safe_name(f"{meta['artist']} — {meta['track']}") + ".mp3"
    final_path     = os.path.join(out_dir, safe_file_name)

    with tempfile.TemporaryDirectory() as tmpdir:
        mp3_path = download_track(sc_track, tmpdir)
        embed_metadata(mp3_path, meta, cover_art)
        shutil.move(mp3_path, final_path)

    log(f"Saved: {final_path}")
    return None
