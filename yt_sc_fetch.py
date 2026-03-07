#!/usr/bin/env python3
"""
yt_sc_fetch.py
--------------
Modes:

  YouTube (auto-search on SoundCloud):
      python3 yt_sc_fetch.py <youtube_url>

  SoundCloud direct (fetch SC metadata, download):
      python3 yt_sc_fetch.py --sc <soundcloud_url>

The YouTube URL can be a single video OR a playlist/album.

Dependencies (install once):
    pip install yt-dlp mutagen
"""

import sys
import os
import re
import math
import json
import subprocess
import tempfile
import shutil
import urllib.request

SC_SEARCH_RESULTS = 10  # results per scsearch query


def log(msg: str) -> None:
    print(f"[yt_sc_fetch] {msg}", flush=True)


def warn(msg: str) -> None:
    print(f"[WARN] {msg}", file=sys.stderr, flush=True)


def die(msg: str) -> None:
    print(f"[ERROR] {msg}", file=sys.stderr)
    sys.exit(1)


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def safe_name(s: str) -> str:
    """Strip characters that are illegal in directory / file names."""
    return re.sub(r'[\\/*?:"<>|]', "_", s).strip()


# ---------------------------------------------------------------------------
# Step 1 – YouTube metadata
# ---------------------------------------------------------------------------

def fetch_playlist_entries(url: str) -> list[dict]:
    """
    Return a list of raw yt-dlp info dicts for every entry in *url*.
    Works for both single videos and playlists/albums.
    """
    log(f"Fetching YouTube entries for: {url}")
    result = run([
        "yt-dlp",
        "--dump-json",   # one JSON object per line
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

    # Only die if we got nothing back (non-zero exit may just be a JS warning)
    if not entries:
        die(f"yt-dlp returned no entries for the given URL.\n{result.stderr}")

    log(f"Found {len(entries)} entry/entries.")
    return entries


def parse_metadata(raw: dict, track_number: int | None = None) -> dict:
    """Extract the fields we care about from a raw yt-dlp info dict."""
    raw_artist = raw.get("artist")
    track = raw.get("track") or raw.get("title") or "Unknown Track"

    if raw_artist:
        artist = raw_artist
    else:
        # Try to split "Artist - Title" or "Artist — Title" from the track name
        m = re.split(r"\s*[—–-]\s*", track, maxsplit=1)
        if len(m) == 2:
            artist = m[0].strip()
            track  = m[1].strip()
        else:
            artist = (
                raw.get("uploader")
                or raw.get("channel")
                or "Unknown Artist"
            )

    # Album artist = first artist when there are multiple (e.g. "A, B, C")
    album_artist = artist.split(",")[0].strip()

    # Build feat. suffix when there are multiple artists
    if album_artist.lower() != artist.lower():
        # Split all artists by comma or ampersand, skip the album artist
        all_artists = [a.strip() for a in re.split(r"[,&]", artist)]
        featuring = [a for a in all_artists if a.lower() != album_artist.lower() and a]

        if featuring:
            feat_str = f"(feat. {', '.join(featuring)})"
            # Only append if none of the featuring artists are already mentioned in the title
            title_lower = track.lower()
            already_present = any(a.lower() in title_lower for a in featuring)
            if not already_present:
                track = f"{track} {feat_str}"

        artist = album_artist

    album = raw.get("album") or raw.get("playlist_title") or "Unknown Album"
    release_year = (
        raw.get("release_year")
        or str(raw.get("release_date", ""))[:4]
        or str(raw.get("upload_date",  ""))[:4]
        or "0000"
    )
    tags     = raw.get("tags") or []
    duration = int(raw.get("duration") or 0)

    return dict(
        artist=artist,
        album_artist=album_artist,
        album=album,
        track=track,
        track_number=track_number,
        release_year=release_year,
        tags=tags,
        duration=duration,
    )


# ---------------------------------------------------------------------------
# Step 2 – SoundCloud search via yt-dlp scsearch extractor
# ---------------------------------------------------------------------------

def _ytdlp_search(query: str, n: int = SC_SEARCH_RESULTS) -> list[dict]:
    search_url = f"scsearch{n}:{query}"
    log(f"  SC search: {search_url!r}")
    result = run([
        "yt-dlp",
        "--dump-json",
        "--flat-playlist",
        "--no-playlist",
        search_url,
    ])
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


def _normalize(s: str) -> str:
    """Lowercase and strip curly/typographic quotes and apostrophes for fuzzy comparison."""
    return s.lower().translate(str.maketrans("\u2018\u2019\u201c\u201d\u02bc\u0060", "''\"\"''"))


def find_best_sc_track(album_artist: str, track_title: str, target_duration: int) -> dict:
    """
    Try two queries in order, return the first track whose:
      • title contains track_title (case-insensitive, punctuation-normalised)
      • duration is within 5% of target_duration — UNLESS album_artist already
        appears in the SC title (could be a clip/edit), in which case duration
        is not checked.
    """
    duration_tolerance = math.ceil(target_duration * 0.05)
    queries = [
        f"{album_artist} {track_title}",
        track_title,
    ]
    needle       = _normalize(track_title)
    artist_lower = _normalize(album_artist)

    for query in queries:
        log(f"Searching SoundCloud: '{query}'")
        results = _ytdlp_search(query)
        log(f"  {len(results)} result(s)")

        for t in results:
            title = _normalize(t.get("title") or "")
            dur   = int(float(t.get("duration") or 0))
            title_ok  = needle in title
            # If the album_artist name is already in the SC title we trust the
            # match and skip the duration gate (might be a shorter clip/edit).
            artist_in_title = artist_lower in title
            dur_ok = artist_in_title or abs(dur - target_duration) <= duration_tolerance

            log(f"  • '{t.get('title')}' | {dur}s "
                f"| title={title_ok} dur={dur_ok} artist_in_title={artist_in_title}")

            if title_ok and dur_ok:
                log(f"  ✓ '{t.get('title')}' @ {t.get('url') or t.get('webpage_url')}")
                return t

    return {}   # caller decides what to do with a miss


# ---------------------------------------------------------------------------
# Download + cover art
# ---------------------------------------------------------------------------

def _track_url(track: dict) -> str:
    return (
        track.get("webpage_url")
        or track.get("url")
        or track.get("permalink_url")
        or ""
    )


def fetch_full_track_info(track: dict) -> dict:
    url = _track_url(track)
    if not url:
        return track
    log(f"Fetching full SC track info: {url}")
    result = run(["yt-dlp", "--dump-json", "--no-playlist", "--skip-download", url])
    if result.returncode != 0:
        return track
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return track


def fetch_cover_art(track_info: dict) -> bytes | None:
    artwork_url = track_info.get("thumbnail") or track_info.get("artwork_url")
    if not artwork_url:
        thumbnails = track_info.get("thumbnails") or []
        if thumbnails:
            best = max(thumbnails, key=lambda t: t.get("width") or t.get("preference") or 0)
            artwork_url = best.get("url")
    if not artwork_url:
        log("No cover art URL found.")
        return None
    artwork_url = re.sub(r"-(large|t500x500)\b", "-original", artwork_url)
    log(f"Fetching cover art: {artwork_url}")
    try:
        req = urllib.request.Request(artwork_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.read()
    except Exception as exc:
        log(f"Warning: could not fetch cover art – {exc}")
        return None


def download_sc_track(track: dict, output_dir: str) -> str:
    url = _track_url(track)
    if not url:
        die("Could not determine a URL for the selected SoundCloud track.")
    log(f"Downloading: {url}")
    output_tmpl = os.path.join(output_dir, "%(id)s.%(ext)s")
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
    for fname in os.listdir(output_dir):
        if fname.endswith(".mp3"):
            return os.path.join(output_dir, fname)
    die("yt-dlp finished but no .mp3 file was produced.")


# ---------------------------------------------------------------------------
# Step 3 – Embed metadata + cover art
# ---------------------------------------------------------------------------

def embed_metadata(mp3_path: str, meta: dict, cover_art: bytes | None) -> None:
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
    tags.add(TPE1(encoding=3, text=meta["artist"]))           # Artist
    tags.add(TPE2(encoding=3, text=meta["album_artist"]))     # Album artist
    tags.add(TALB(encoding=3, text=meta["album"]))            # Album
    tags.add(TIT2(encoding=3, text=meta["track"]))            # Title
    tags.add(TDRC(encoding=3, text=str(meta["release_year"])))  # Year

    if meta.get("track_number") is not None:
        tags.add(TRCK(encoding=3, text=str(meta["track_number"])))  # Track number (playlist position)

    if meta["tags"]:
        tags.add(TCON(encoding=3, text="; ".join(meta["tags"][:5])))

    if cover_art:
        mime = "image/png" if cover_art[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"
        tags.add(APIC(encoding=3, mime=mime, type=3, desc="Cover", data=cover_art))

    tags.save(mp3_path, v2_version=3)
    log("Metadata embedded.")


# ---------------------------------------------------------------------------
# Process a single track entry end-to-end
# ---------------------------------------------------------------------------

def process_entry(raw: dict, output_dir: str, track_number: int | None = None) -> str | None:
    """
    Process one YouTube entry (video).
    Returns None on success, or a human-readable label string if skipped.
    """
    meta = parse_metadata(raw, track_number=track_number)
    log(f"\n── Track: {meta['artist']} – {meta['track']} ({meta['duration']}s)")

    # Find on SoundCloud
    sc_track = find_best_sc_track(meta["album_artist"], meta["track"], meta["duration"])
    if not sc_track:
        label = f"{meta['artist']} – {meta['track']}"
        warn(f"Skipping '{label}': no matching SoundCloud track found.")
        return label

    sc_track_full = fetch_full_track_info(sc_track)
    cover_art     = fetch_cover_art(sc_track_full)

    # Build output path:  output/<album_artist>/<album>/<artist> — <track>.mp3
    out_dir = os.path.join(output_dir, safe_name(meta["album_artist"]), safe_name(meta["album"]))
    os.makedirs(out_dir, exist_ok=True)
    safe_file_name = safe_name(f"{meta['artist']} — {meta['track']}") + ".mp3"
    final_path = os.path.join(out_dir, safe_file_name)

    # Download into a temp dir, tag, then move into place
    with tempfile.TemporaryDirectory() as tmpdir:
        mp3_path = download_sc_track(sc_track, tmpdir)
        embed_metadata(mp3_path, meta, cover_art)
        shutil.move(mp3_path, final_path)

    log(f"Saved: {final_path}")
    return None


# ---------------------------------------------------------------------------
# SoundCloud direct mode
# ---------------------------------------------------------------------------

def fetch_sc_entries(sc_url: str) -> list[dict]:
    """
    Fetch all track entries from a SoundCloud URL via yt-dlp.
    Works for single tracks, playlists, and albums.
    """
    log(f"Fetching SoundCloud entries for: {sc_url}")
    result = run([
        "yt-dlp",
        "--dump-json",
        "--yes-playlist",
        "--skip-download",
        sc_url,
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
        die(f"yt-dlp returned no entries for SoundCloud URL.\n{result.stderr}")
    log(f"Found {len(entries)} SC entry/entries.")
    return entries


def parse_sc_metadata(raw: dict, track_number: int | None = None) -> dict:
    """
    Extract metadata from a SoundCloud yt-dlp info dict.
    SoundCloud fields: uploader = artist name, title = track title.
    """
    artist       = raw.get("uploader") or raw.get("channel") or "Unknown Artist"
    album_artist = artist.split(",")[0].strip()
    track        = raw.get("title") or "Unknown Track"
    album        = raw.get("album") or raw.get("playlist_title") or "Unknown Album"
    release_year = (
        str(raw.get("release_date", ""))[:4]
        or str(raw.get("upload_date",  ""))[:4]
        or "0000"
    )
    tags     = raw.get("tags") or []
    duration = int(raw.get("duration") or 0)

    return dict(
        artist=artist,
        album_artist=album_artist,
        album=album,
        track=track,
        track_number=track_number,
        release_year=release_year,
        tags=tags,
        duration=duration,
    )


def display_metadata(meta: dict) -> None:
    """Pretty-print metadata so the user can review it."""
    print("\n┌─ Metadata ─────────────────────────────")
    print(f"│  Artist       : {meta['artist']}")
    print(f"│  Album artist : {meta['album_artist']}")
    print(f"│  Album        : {meta['album']}")
    print(f"│  Track        : {meta['track']}")
    if meta.get("track_number") is not None:
        print(f"│  Track #      : {meta['track_number']}")
    print(f"│  Year         : {meta['release_year']}")
    print(f"│  Duration     : {meta['duration']}s")
    if meta['tags']:
        print(f"│  Tags         : {', '.join(meta['tags'][:8])}")
    print("└────────────────────────────────────────\n")


def process_sc_entry(raw: dict, output_dir: str, track_number: int | None = None) -> None:
    """Parse SC metadata from one raw entry, display it, download and tag."""
    meta      = parse_sc_metadata(raw, track_number=track_number)
    cover_art = fetch_cover_art(raw)

    display_metadata(meta)

    # Build output path:  output/<album_artist>/<album>/<artist> — <track>.mp3
    out_dir = os.path.join(output_dir, safe_name(meta["album_artist"]), safe_name(meta["album"]))
    os.makedirs(out_dir, exist_ok=True)
    safe_file_name = safe_name(f"{meta['artist']} — {meta['track']}") + ".mp3"
    final_path = os.path.join(out_dir, safe_file_name)

    sc_track = {
        "webpage_url": raw.get("webpage_url") or raw.get("url"),
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        mp3_path = download_sc_track(sc_track, tmpdir)
        embed_metadata(mp3_path, meta, cover_art)
        shutil.move(mp3_path, final_path)

    log(f"Saved: {final_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    # -- SoundCloud direct mode --
    if len(sys.argv) == 3 and sys.argv[1] == "--sc":
        sc_url     = sys.argv[2]
        output_dir = "output"
        os.makedirs(output_dir, exist_ok=True)

        entries     = fetch_sc_entries(sc_url)
        is_playlist = len(entries) > 1

        for i, raw in enumerate(entries, 1):
            if is_playlist:
                log(f"\n[{i}/{len(entries)}]")
            track_number = i if is_playlist else None
            process_sc_entry(raw, output_dir, track_number=track_number)

        log(f"\nFinished. {len(entries)} track(s) downloaded.")
        return

    # -- YouTube mode --
    if len(sys.argv) != 2:
        print(f"Usage:")
        print(f"  {sys.argv[0]} <youtube_url_or_playlist>")
        print(f"  {sys.argv[0]} --sc <soundcloud_url_or_playlist>")
        sys.exit(1)

    yt_url  = sys.argv[1]
    entries = fetch_playlist_entries(yt_url)

    output_dir = "output"
    os.makedirs(output_dir, exist_ok=True)

    skipped_tracks: list[str] = []
    is_playlist = len(entries) > 1
    for i, raw in enumerate(entries, 1):
        log(f"\n[{i}/{len(entries)}]")
        track_number = i if is_playlist else None
        skipped = process_entry(raw, output_dir=output_dir, track_number=track_number)
        if skipped:
            skipped_tracks.append(f"  {len(skipped_tracks) + 1}. {skipped}")

    ok = len(entries) - len(skipped_tracks)
    log(f"\nFinished. {ok} downloaded, {len(skipped_tracks)} skipped.")
    if skipped_tracks:
        print("\nSkipped tracks:")
        print("\n".join(skipped_tracks))


if __name__ == "__main__":
    main()