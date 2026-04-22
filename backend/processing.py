import base64
import logging
import os
import re
import tempfile
import shutil
from typing import Any, Optional

from fix_artists import split_artist
from models import ProcessRequest, ScProcessRequest, TrackMeta

logger = logging.getLogger(__name__)


def _safe(s: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "_", s).strip()


def _to_list(raw: Any) -> list[str]:
    """Normalise a tag value (str or list) into a list of trimmed artist names."""
    if raw is None:
        return []
    if isinstance(raw, list):
        items: list[str] = []
        for x in raw:
            s = str(x).strip()
            if s:
                items.extend(split_artist(s) or [s])
        return items
    s = str(raw).strip()
    if not s:
        return []
    return split_artist(s) or [s]


def _folder_name(artists: list[str]) -> str:
    """Folder name for the artist — first entry, or empty string."""
    return artists[0] if artists else ""


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

    # Duration in seconds (mutagen exposes .info.length for all formats)
    duration: Optional[int] = None
    codec: Optional[str] = None
    bitrate: Optional[int] = None  # kbps
    try:
        info = audio.info
        length = getattr(info, "length", None)
        if length is not None:
            duration = int(round(length))
        # Bitrate: mutagen stores it in bps for most formats
        br = getattr(info, "bitrate", None)
        if br:
            bitrate = int(round(br / 1000)) if br > 1000 else int(br)
        # Codec detection by class name / mime_type
        cls = type(audio).__name__
        mime = getattr(audio, "mime", [])
        mime0 = mime[0] if mime else ""
        if "FLAC" in cls or "flac" in mime0:
            codec = "FLAC"
        elif "MP3" in cls or "mp3" in mime0:
            codec = "MP3"
        elif "OggVorbis" in cls or "ogg" in mime0 and "vorbis" in mime0:
            codec = "OGG"
        elif "OggOpus" in cls or "opus" in mime0:
            codec = "Opus"
        elif "MP4" in cls or "mp4" in mime0 or "m4a" in mime0:
            codec = "AAC"
        elif "Wave" in cls or "wav" in mime0:
            codec = "WAV"
        elif "AIFF" in cls or "aiff" in mime0:
            codec = "AIFF"
        elif cls:
            codec = cls.split(".")[-1].upper()[:6]
    except Exception:
        pass

    tags = audio.tags
    if tags is None:
        return _empty_meta(path, file_name, index, duration)

    # ID3 (MP3): has getall(); Vorbis comment (FLAC/OGG): doesn't
    is_id3 = hasattr(tags, "getall")

    def _id3(key: str) -> str:
        frame = tags.get(key)
        return str(frame.text[0]).strip() if frame and frame.text else ""

    def _vorbis(key: str) -> str:
        val = tags.get(key)
        return str(val[0]).strip() if val else ""

    def _id3_list(key: str) -> list[str]:
        frame = tags.get(key)
        if not frame or not frame.text:
            return []
        items: list[str] = []
        for v in frame.text:
            s = str(v).strip()
            if s:
                items.extend(split_artist(s) or [s])
        return items

    if is_id3:
        title = _id3("TIT2")
        artists = _id3_list("TPE1")
        album_artists = _id3_list("TPE2")
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

        composer = _id3("TCOM")
        language = _id3("TLAN")
        lyrics_frame = tags.get("USLT::")
        if lyrics_frame is None:
            uslt_keys = [k for k in tags.keys() if k.startswith("USLT")]
            lyrics_frame = tags[uslt_keys[0]] if uslt_keys else None
        lyrics = lyrics_frame.text if lyrics_frame else None

    else:
        # Vorbis comment (FLAC, OGG, Opus…)
        title = _vorbis("title")
        artists = _to_list(tags.get("artist") or [])
        album_artists = _to_list(tags.get("albumartist") or [])
        album = _vorbis("album")
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

        composer = _vorbis("composer")
        language = _vorbis("language")
        lyrics = _vorbis("lyrics") or _vorbis("unsyncedlyrics") or None

    # album_artists defaults to artists when the tag wasn't set or matches
    if not album_artists:
        album_artists = list(artists)
    return TrackMeta(
        temp_path=path,
        file_name=file_name,
        title=title,
        artists=artists,
        album_artists=album_artists,
        album=album,
        release_year=release_year,
        track_number=track_number,
        cover_art_b64=cover_art_b64,
        duration=duration,
        codec=codec,
        bitrate=bitrate,
        composer=composer or None,
        language=language or None,
        lyrics=lyrics or None,
    )


def _empty_meta(
    path: str, file_name: str, index: int, duration: Optional[int] = None
) -> TrackMeta:
    return TrackMeta(
        temp_path=path,
        file_name=file_name,
        title="",
        artists=[],
        album_artists=[],
        album="",
        release_year="",
        track_number=index,
        duration=duration,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _track_filename(t: TrackMeta, is_single: bool, ext: str) -> str:
    if is_single:
        return _safe(t.title) + ext
    return _safe(f"{t.track_number:02d} {t.title}") + ext


# ---------------------------------------------------------------------------
# Upload files directly to SFTP album folder
# ---------------------------------------------------------------------------


def process_album(req: ProcessRequest) -> list[str]:
    """
    Embed corrected metadata into every track, then upload directly to
      <SFTP_BASE>/<album_artist>/<album>/<filename>

    Also writes cover.jpg and a .album control file into the same folder.
    The .album file marks needs_processing=true when the album contains files
    with more than one distinct audio extension (mixed formats).

    Returns the list of remote paths.
    """
    from services.sftp import (
        album_path,
        track_path,
        upload_cover,
        upload_file,
        write_album_file,
    )
    from soundcloud.tagger import embed_tags
    from fix_artists import sanitize_m4a_streams
    import base64

    if not req.album_artists:
        req = req.model_copy(update={"album_artists": list(req.artists)})
    folder_artist = _folder_name(req.album_artists)

    # Decode shared album cover
    shared_cover: Optional[bytes] = None
    if req.cover_art_b64:
        try:
            shared_cover = base64.b64decode(req.cover_art_b64)
        except Exception:
            pass

    # Determine whether the album needs processing (mixed extensions)
    extensions = {
        os.path.splitext(t.temp_path)[1].lower() or ".mp3"
        for t in req.tracks
    }
    needs_processing = len(extensions) > 1

    saved = []
    for t in req.tracks:
        ext = os.path.splitext(t.temp_path)[1].lower() or ".mp3"
        fname = _track_filename(t, req.is_single, ext)
        if req.is_single:
            remote_path = track_path(_safe(folder_artist), fname)
        else:
            remote_path = album_path(_safe(folder_artist), _safe(req.album), fname)

        # Per-track cover takes priority over album cover
        cover: Optional[bytes] = shared_cover
        if t.cover_art_b64:
            try:
                cover = base64.b64decode(t.cover_art_b64)
            except Exception:
                pass

        meta = {
            "title": t.title,
            "artists": list(req.artists),
            "album_artists": list(req.album_artists),
            "album": "" if req.is_single else req.album,
            "release_year": req.release_year,
            "track_number": t.track_number,
        }

        try:
            logger.info(
                "sanitize: checking %s (ext=%s)",
                os.path.basename(t.temp_path),
                os.path.splitext(t.temp_path)[1].lower(),
            )
            sanitize_m4a_streams(t.temp_path)
            embed_tags(t.temp_path, meta, cover)
        except Exception as exc:
            logger.warning("Could not embed tags into %s: %s", t.temp_path, exc)

        logger.info(
            "Uploading via SFTP: %s → %s", os.path.basename(t.temp_path), remote_path
        )
        upload_file(t.temp_path, remote_path)

        # Clean up local temp file after successful upload
        try:
            os.unlink(t.temp_path)
        except OSError:
            pass

        saved.append(remote_path)

    # Singles land directly under the artist folder — no cover.jpg or
    # .album file (cover is embedded in the track; no album to process).
    if not req.is_single:
        # Upload cover.jpg into the album folder (use shared cover; fall back
        # to the first track's individual cover if there is no shared one)
        cover_bytes: Optional[bytes] = shared_cover
        if cover_bytes is None and req.tracks:
            first_track_cover = req.tracks[0].cover_art_b64
            if first_track_cover:
                try:
                    cover_bytes = base64.b64decode(first_track_cover)
                except Exception:
                    pass
        if cover_bytes:
            cover_path = upload_cover(
                cover_bytes, _safe(folder_artist), _safe(req.album)
            )
            if cover_path:
                saved.append(cover_path)
                logger.info("Uploaded cover.jpg → %s", cover_path)

        album_file_path = write_album_file(
            _safe(folder_artist), _safe(req.album), needs_processing
        )
        if album_file_path:
            saved.append(album_file_path)

    # If all tracks came from a zip subdir, remove the now-empty directory
    dirs = {os.path.dirname(t.temp_path) for t in req.tracks}
    for d in dirs:
        try:
            if d and os.path.isdir(d) and not os.listdir(d):
                os.rmdir(d)
        except OSError:
            pass

    return saved


# ---------------------------------------------------------------------------
# Download SoundCloud tracks, tag them, upload directly to SFTP album folder
# ---------------------------------------------------------------------------


async def process_sc_album(req: ScProcessRequest) -> list[str]:
    """
    Download SoundCloud tracks, embed metadata + cover art, then upload directly to
      <SFTP_BASE>/<album_artist>/<album>/<filename>

    Also writes cover.jpg and a .album control file into the same folder.
    For SoundCloud downloads the format is always uniform (yt-dlp picks one
    best format per track), so needs_processing is determined by whether the
    resulting files have mixed extensions.

    Returns the list of remote paths.
    """
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    from soundcloud.downloader import download_raw
    from soundcloud.tagger import embed_tags
    from services.sftp import (
        album_path,
        track_path,
        upload_cover,
        upload_file,
        write_album_file,
    )

    _executor = ThreadPoolExecutor(max_workers=4)

    def _run_in_thread(fn, *args):
        loop = asyncio.get_event_loop()
        return loop.run_in_executor(_executor, fn, *args)

    if not req.album_artists:
        req = req.model_copy(update={"album_artists": list(req.artists)})
    folder_artist = _folder_name(req.album_artists)

    # Decode shared album cover (used when a track has no individual cover)
    shared_cover: Optional[bytes] = None
    if req.cover_art_b64:
        try:
            shared_cover = base64.b64decode(req.cover_art_b64)
        except Exception:
            pass

    saved = []
    first_cover: Optional[bytes] = None  # fallback if no shared cover
    downloaded_exts: set[str] = set()  # track extensions to detect mixed formats

    for t in req.tracks:
        if not t.sc_url:
            raise ValueError(f"Missing sc_url for track '{t.title}'")

        # Per-track cover takes priority over album cover
        cover: Optional[bytes] = shared_cover
        if t.cover_art_b64:
            try:
                cover = base64.b64decode(t.cover_art_b64)
            except Exception:
                pass

        if first_cover is None and cover:
            first_cover = cover

        track_artists = list(t.artists) if t.artists else list(req.artists)
        meta = {
            "title": t.title,
            "artists": track_artists,
            "album_artists": list(req.album_artists),
            "album": "" if req.is_single else req.album,
            "release_year": req.release_year,
            "track_number": t.track_number,
        }

        tmp_dir = tempfile.mkdtemp(prefix="sc_dl_")
        try:
            logger.info("Downloading SC track: %r", t.sc_url)
            raw_file = await _run_in_thread(download_raw, t.sc_url, tmp_dir)

            ext = os.path.splitext(raw_file)[1].lower()
            downloaded_exts.add(ext)
            fname = _track_filename(t, req.is_single, ext)
            if req.is_single:
                remote_path = track_path(_safe(folder_artist), fname)
            else:
                remote_path = album_path(_safe(folder_artist), _safe(req.album), fname)

            embed_tags(raw_file, meta, cover)

            logger.info("Uploading via SFTP: %s → %s", fname, remote_path)
            await _run_in_thread(upload_file, raw_file, remote_path)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        saved.append(remote_path)

    # Singles land directly under the artist folder — skip cover.jpg and
    # .album control file (no album to scan).
    if not req.is_single:
        cover_bytes: Optional[bytes] = shared_cover or first_cover
        if cover_bytes:
            cover_path = await _run_in_thread(
                upload_cover, cover_bytes, _safe(folder_artist), _safe(req.album)
            )
            if cover_path:
                saved.append(cover_path)
                logger.info("Uploaded cover.jpg → %s", cover_path)

        needs_processing = len(downloaded_exts) > 1
        album_file_path = await _run_in_thread(
            write_album_file, _safe(folder_artist), _safe(req.album), needs_processing
        )
        if album_file_path:
            saved.append(album_file_path)

    return saved
