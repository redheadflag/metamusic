import re
from .utils import die


def _normalize(s: str) -> str:
    """Lowercase and strip typographic quotes/apostrophes for fuzzy comparison."""
    return s.lower().translate(
        str.maketrans("\u2018\u2019\u201c\u201d\u02bc\u0060", "''\"\"''")
    )


# ---------------------------------------------------------------------------
# YouTube metadata
# ---------------------------------------------------------------------------


def parse_yt_metadata(raw: dict, track_number: int | None = None) -> dict:
    """Extract and normalise metadata from a raw yt-dlp YouTube info dict."""
    raw_artist = raw.get("artist")
    track = raw.get("track") or raw.get("title") or "Unknown Track"

    if raw_artist:
        artist = raw_artist
    else:
        # Try to split "Artist - Title" or "Artist — Title" from the track name
        m = re.split(r"\s*[—–-]\s*", track, maxsplit=1)
        if len(m) == 2:
            artist = m[0].strip()
            track = m[1].strip()
        else:
            artist = raw.get("uploader") or raw.get("channel") or "Unknown Artist"

    # Album artist = first artist when there are multiple (e.g. "A, B, C")
    album_artist = artist.split(",")[0].strip()

    # Build feat. suffix when there are multiple artists
    if album_artist.lower() != artist.lower():
        all_artists = [a.strip() for a in re.split(r"[,&]", artist)]
        featuring = [a for a in all_artists if a.lower() != album_artist.lower() and a]

        if featuring:
            feat_str = f"(feat. {', '.join(featuring)})"
            already_present = any(a.lower() in track.lower() for a in featuring)
            if not already_present:
                track = f"{track} {feat_str}"

    # artist always matches album_artist
    artist = album_artist
    album = raw.get("album") or raw.get("playlist_title") or f"{track} (Single)"

    release_year = (
        raw.get("release_year")
        or str(raw.get("release_date", ""))[:4]
        or str(raw.get("upload_date", ""))[:4]
        or "0000"
    )
    tags = raw.get("tags") or []
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
# SoundCloud metadata
# ---------------------------------------------------------------------------


def parse_sc_metadata(raw: dict, track_number: int | None = None) -> dict:
    """Extract and normalise metadata from a raw yt-dlp SoundCloud info dict."""
    artist = raw.get("uploader") or raw.get("channel") or "Unknown Artist"
    album_artist = artist.split(",")[0].strip()
    artist = album_artist  # always matches album_artist
    track = raw.get("title") or "Unknown Track"
    album = raw.get("album") or raw.get("playlist_title") or f"{track} (Single)"
    release_year = (
        str(raw.get("release_date", ""))[:4]
        or str(raw.get("upload_date", ""))[:4]
        or "0000"
    )
    tags = raw.get("tags") or []
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
# Overrides & validation
# ---------------------------------------------------------------------------


def apply_sc_overrides(meta: dict, overrides: dict) -> dict:
    """Merge user-supplied override values into a parsed meta dict."""
    meta = dict(meta)
    if overrides.get("artist"):
        meta["artist"] = overrides["artist"]
        meta["album_artist"] = overrides["artist"].split(",")[0].strip()
    if overrides.get("album_artist"):
        meta["album_artist"] = overrides["album_artist"]
    if overrides.get("album"):
        meta["album"] = overrides["album"]
    if overrides.get("track"):
        meta["track"] = overrides["track"]
    if overrides.get("year"):
        meta["release_year"] = overrides["year"]
    return meta


def validate_sc_overrides(overrides: dict, is_playlist: bool) -> None:
    """
    When any override is supplied, enforce that all required fields are present.
    Required always:            --artist, --album, --year
    Required for single track:  --track
    """
    missing = [f"--{k}" for k in ("artist", "album", "year") if not overrides.get(k)]
    if not is_playlist and not overrides.get("track"):
        missing.append("--track")
    if missing:
        die(
            "When passing metadata overrides the following arguments are also required: "
            + ", ".join(missing)
        )


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------


def display_metadata(meta: dict) -> None:
    """Pretty-print a metadata dict for the user to review."""
    print("\n┌─ Metadata ─────────────────────────────")
    print(f"│  Artist       : {meta['artist']}")
    print(f"│  Album artist : {meta['album_artist']}")
    print(f"│  Album        : {meta['album']}")
    print(f"│  Track        : {meta['track']}")
    if meta.get("track_number") is not None:
        print(f"│  Track #      : {meta['track_number']}")
    print(f"│  Year         : {meta['release_year']}")
    print(f"│  Duration     : {meta['duration']}s")
    if meta.get("tags"):
        print(f"│  Tags         : {', '.join(meta['tags'][:8])}")
    print("└────────────────────────────────────────\n")
