import base64
import logging
import os
import re
import shutil
import tempfile
from typing import Optional

from models import ProcessRequest, ScProcessRequest, TrackMeta

logger = logging.getLogger(__name__)

MUSIC_LIBRARY_PATH = "/music"


def _safe(s: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "_", s).strip()


def _find_ci(parent: str, name: str) -> str:
    """
    Return `parent/name`, using a case-insensitive match against existing
    entries. Falls back to the exact name.
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
    Split multiple artists into a single album_artist + (feat. ...) in title.
    e.g. artist="Gone.Fludd, LSP" title="Uti-Puti"
      -> artist="Gone.Fludd"  title="Uti-Puti (feat. LSP)"
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
    except ImportError:
        return _empty_meta(path, file_name, index)

    audio = MutagenFile(path, easy=False)
    if audio is None:
        return _empty_meta(path, file_name, index)

    tags = audio.tags
    if tags is None:
        return _empty_meta(path, file_name, index)

    # ID3 (MP3): has getall(); Vorbis comment (FLAC/OGG): doesn't
    is_id3 = hasattr(tags, "getall")

    def _id3(key: str) -> str:
        frame = tags.get(key)
        return str(frame.text[0]).strip() if frame and frame.text else ""

    def _vorbis(key: str) -> str:
        val = tags.get(key)
        return str(val[0]).strip() if val else ""

    if is_id3:
        title        = _id3("TIT2")
        artist       = _id3("TPE1")
        album_artist = _id3("TPE2")
        album        = _id3("TALB")
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

        composer  = _id3("TCOM")
        publisher = _id3("TPUB")
        language  = _id3("TLAN")
        lyrics_frame = tags.get("USLT::")
        if lyrics_frame is None:
            uslt_keys = [k for k in tags.keys() if k.startswith("USLT")]
            lyrics_frame = tags[uslt_keys[0]] if uslt_keys else None
        lyrics = lyrics_frame.text if lyrics_frame else None

    else:
        # Vorbis comment (FLAC, OGG, Opus…)
        title        = _vorbis("title")
        artist       = ", ".join(v.strip() for v in (tags.get("artist") or []) if v.strip()) or ""
        album_artist = _vorbis("albumartist")
        album        = _vorbis("album")
        release_year = _vorbis("date")

        track_number = index
        trckval = _vorbis("tracknumber")
        if trckval:
            try:
                track_number = int(trckval.split("/")[0])
            except ValueError:
                pass

        cover_art_b64 = None
        pictures = getattr(audio, "pictures", [])
        if pictures:
            cover_art_b64 = base64.b64encode(pictures[0].data).decode()

        composer  = _vorbis("composer")
        publisher = _vorbis("organization") or _vorbis("publisher")
        language  = _vorbis("language")
        lyrics    = _vorbis("lyrics") or _vorbis("unsyncedlyrics") or None

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
# Store uploaded files (raw, no conversion)
# ---------------------------------------------------------------------------


def _build_dest_path(req: ProcessRequest, t: TrackMeta, is_single: bool) -> str:
    src_ext = os.path.splitext(t.temp_path)[1].lower() or ".mp3"
    artist_dir = _find_ci(MUSIC_LIBRARY_PATH, _safe(req.album_artist))
    out_dir    = _find_ci(artist_dir, _safe(req.album))
    os.makedirs(out_dir, exist_ok=True)
    fname = (
        _safe(t.title) + src_ext
        if is_single
        else _safe(f"{t.track_number:02d} {t.title}") + src_ext
    )
    return _find_ci(out_dir, fname)


def process_album(req: ProcessRequest) -> list[str]:
    """
    Copy every uploaded track (raw, unprocessed) into MUSIC_LIBRARY_PATH,
    preserving the original file format (FLAC, M4A, MP3, …).

    The external processor service handles conversion and metadata embedding.
    """
    saved = []
    for t in req.tracks:
        dest = _build_dest_path(req, t, req.is_single)
        logger.info("Storing raw file: %s → %s", os.path.basename(t.temp_path), dest)
        if os.path.abspath(t.temp_path) != os.path.abspath(dest):
            shutil.copy2(t.temp_path, dest)
            os.unlink(t.temp_path)
        saved.append(dest)
    return saved


# ---------------------------------------------------------------------------
# Download SoundCloud tracks and store raw
# ---------------------------------------------------------------------------


async def process_sc_album(req: ScProcessRequest) -> list[str]:
    """
    Download SoundCloud tracks in their native audio format and store them raw
    under MUSIC_LIBRARY_PATH.  No conversion — the external processor service
    handles that on the more powerful machine.
    """
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    from soundcloud.downloader import download_raw

    _executor = ThreadPoolExecutor(max_workers=4)

    def _run_in_thread(fn, *args):
        loop = asyncio.get_event_loop()
        return loop.run_in_executor(_executor, fn, *args)

    if not req.album_artist:
        req = req.model_copy(update={"album_artist": req.artist})
    if req.is_single and not req.album:
        req = req.model_copy(update={"album": f"{req.tracks[0].title} (Single)"})

    saved = []
    for t in req.tracks:
        if not t.sc_url:
            raise ValueError(f"Missing sc_url for track '{t.title}'")

        artist_dir = _find_ci(MUSIC_LIBRARY_PATH, _safe(req.album_artist))
        out_dir    = _find_ci(artist_dir, _safe(req.album))
        os.makedirs(out_dir, exist_ok=True)

        base_name = (
            _safe(t.title)
            if req.is_single
            else _safe(f"{t.track_number:02d} {t.title}")
        )

        logger.info("Downloading SC track (raw): %r → %s/", t.sc_url, out_dir)
        tmp_dir = tempfile.mkdtemp(prefix="sc_dl_")
        try:
            raw_file = await _run_in_thread(download_raw, t.sc_url, tmp_dir)
            ext  = os.path.splitext(raw_file)[1]
            dest = _find_ci(out_dir, base_name + ext)
            shutil.move(raw_file, dest)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        saved.append(dest)

    return saved
