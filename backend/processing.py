import base64
import logging
import os
import re
import shutil
from typing import Optional

from models import TrackMeta, ProcessRequest

logger = logging.getLogger(__name__)

MUSIC_LIBRARY_PATH = os.environ.get("MUSIC_LIBRARY_PATH", "/music")


def _safe(s: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "_", s).strip()


def _find_ci(parent: str, name: str) -> str:
    """
    Return the path `parent/name`, using a case-insensitive match if an
    existing entry differs only in case. Falls back to the exact name.
    """
    if not os.path.isdir(parent):
        return os.path.join(parent, name)
    name_lower = name.lower()
    for entry in os.listdir(parent):
        if entry.lower() == name_lower:
            return os.path.join(parent, entry)
    return os.path.join(parent, name)


def _normalize_artists(artist: str, title: str) -> tuple[str, str]:
    """
    Split multiple artists into a single album_artist + (feat. ...) in the title.
    e.g. artist="Gone.Fludd, ЛСП" title="Ути-Пути"
      -> artist="Gone.Fludd"  title="Ути-Пути (feat. ЛСП)"
    """
    parts = [a.strip() for a in re.split(r"[,&/;\\]", artist) if a.strip()]
    if len(parts) <= 1:
        return artist, title

    main = parts[0]
    featuring = parts[1:]

    already_present = any(f.lower() in title.lower() for f in featuring)
    if not already_present:
        feat_str = f"(feat. {', '.join(featuring)})"
        title = f"{title} {feat_str}"

    return main, title


# ---------------------------------------------------------------------------
# Read tags from an uploaded file (any format mutagen supports)
# ---------------------------------------------------------------------------


def read_tags(path: str, file_name: str, index: int) -> TrackMeta:
    try:
        from mutagen import File as MutagenFile
        from mutagen.id3 import ID3
    except ImportError:
        return _empty_meta(path, file_name, index)

    audio = MutagenFile(path, easy=False)
    if audio is None:
        return _empty_meta(path, file_name, index)

    tags = audio.tags
    if tags is None:
        return _empty_meta(path, file_name, index)

    # Vorbis comments (FLAC, OGG) use plain lowercase string keys
    # ID3 (MP3) uses frame objects — detected by presence of ID3 attribute
    is_id3 = hasattr(tags, "getall")  # mutagen ID3 has getall(); VorbisComment doesn't

    def _id3(key: str) -> str:
        frame = tags.get(key)
        return str(frame.text[0]).strip() if frame and frame.text else ""

    def _vorbis(key: str) -> str:
        val = tags.get(key)
        return str(val[0]).strip() if val else ""

    if is_id3:
        title = _id3("TIT2")
        artist = _id3("TPE1")
        album_artist = _id3("TPE2")
        album = _id3("TALB")
        release_year = _id3("TDRC")

        track_number = index
        trck = tags.get("TRCK")
        if trck and trck.text:
            try:
                track_number = int(str(trck.text[0]).split("/")[0])
            except ValueError:
                pass

        cover_art_b64: Optional[str] = None
        apic_keys = [k for k in tags.keys() if k.startswith("APIC")]
        if apic_keys:
            cover_art_b64 = base64.b64encode(tags[apic_keys[0]].data).decode()

        # optional tags
        composer = _id3("TCOM")
        publisher = _id3("TPUB")
        language = _id3("TLAN")
        lyrics_frame = tags.get("USLT::")
        if lyrics_frame is None:
            uslt_keys = [k for k in tags.keys() if k.startswith("USLT")]
            lyrics_frame = tags[uslt_keys[0]] if uslt_keys else None
        lyrics = lyrics_frame.text if lyrics_frame else None

    else:
        # Vorbis comment (FLAC, OGG, Opus…)
        title = _vorbis("title")
        artist = (
            ", ".join(v.strip() for v in (tags.get("artist") or []) if v.strip()) or ""
        )
        album_artist = _vorbis("albumartist")
        album = _vorbis("album")
        release_year = _vorbis("date")

        track_number = index
        trckval = _vorbis("tracknumber")
        if trckval:
            try:
                track_number = int(trckval.split("/")[0])
            except ValueError:
                pass

        # FLAC cover art lives in audio.pictures, not in tags
        cover_art_b64 = None
        pictures = getattr(audio, "pictures", [])
        if pictures:
            cover_art_b64 = base64.b64encode(pictures[0].data).decode()

        # optional tags
        composer = _vorbis("composer")
        publisher = _vorbis("organization") or _vorbis("publisher")
        language = _vorbis("language")
        lyrics = _vorbis("lyrics") or _vorbis("unsyncedlyrics") or None

    artist, title = _normalize_artists(artist, title)
    return TrackMeta(
        temp_path=path,
        file_name=file_name,
        title=title,
        artist=artist,
        album_artist=album_artist or artist,
        album=album,
        release_year=release_year,
        track_number=track_number,
        cover_art_b64=cover_art_b64,
        composer=composer or None,
        language=language or None,
        lyrics=lyrics or None,
    )


def _empty_meta(path: str, file_name: str, index: int) -> TrackMeta:
    return TrackMeta(
        temp_path=path,
        file_name=file_name,
        title="",
        artist="",
        album_artist="",
        album="",
        release_year="",
        track_number=index,
    )


# ---------------------------------------------------------------------------
# Save raw files to MUSIC_LIBRARY_PATH (no FFmpeg — processing happens
# on the separate processor service that reads from this folder)
# ---------------------------------------------------------------------------


def _build_dest_path(
    req: ProcessRequest,
    t: TrackMeta,
    is_single: bool,
) -> str:
    """Return the destination path under MUSIC_LIBRARY_PATH, preserving the
    original file extension so the processor service receives the raw format."""
    src_ext = os.path.splitext(t.temp_path)[1].lower() or ".mp3"

    artist_dir = _find_ci(MUSIC_LIBRARY_PATH, _safe(req.album_artist))
    out_dir = _find_ci(artist_dir, _safe(req.album))
    os.makedirs(out_dir, exist_ok=True)

    if is_single:
        fname = _safe(t.title) + src_ext
    else:
        fname = _safe(f"{t.track_number:02d} {t.title}") + src_ext

    return _find_ci(out_dir, fname)


def process_album(req: ProcessRequest) -> list[str]:
    """
    Copy every uploaded track (raw, unprocessed) into MUSIC_LIBRARY_PATH,
    preserving the original file format (FLAC, M4A, MP3, …).

    FFmpeg conversion and metadata embedding are handled by the standalone
    processor service that reads from this same folder on the powerful machine.

    Single track uploads get album = "<title> (Single)" and no track-number prefix.
    """
    is_single = req.is_single

    saved = []
    for t in req.tracks:
        dest = _build_dest_path(req, t, is_single)

        logger.info(
            "Storing raw file: %s → %s",
            os.path.basename(t.temp_path),
            dest,
        )
        if os.path.abspath(t.temp_path) != os.path.abspath(dest):
            shutil.copy2(t.temp_path, dest)
            os.unlink(t.temp_path)
        saved.append(dest)

    return saved