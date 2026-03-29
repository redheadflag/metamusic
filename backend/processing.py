import base64
import logging
import os
import re
import tempfile
import shutil
from typing import Optional

from models import ProcessRequest, ScProcessRequest, TrackMeta

logger = logging.getLogger(__name__)


def _safe(s: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "_", s).strip()


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

        cover_art_b64 = None
        pictures = getattr(audio, "pictures", [])
        if pictures:
            cover_art_b64 = base64.b64encode(pictures[0].data).decode()

        composer = _vorbis("composer")
        language = _vorbis("language")
        lyrics = _vorbis("lyrics") or _vorbis("unsyncedlyrics") or None

    artist, title = _normalize_artists(artist, title)
    # album_artist must always match artist — never use a separate value
    return TrackMeta(
        temp_path=path,
        file_name=file_name,
        title=title,
        artist=artist,
        album_artist=artist,
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
        artist="",
        album_artist="",
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
# Upload uploaded files to SFTP unprocessed/
# ---------------------------------------------------------------------------


def process_album(req: ProcessRequest) -> list[str]:
    """
    Embed corrected metadata into every track, then upload (raw) to
      <SFTP_BASE>/unprocessed/<album_artist>/<album>/<filename>

    Also writes cover.jpg into the same folder when cover art is present.

    Returns the list of remote paths.
    """
    from services.sftp import upload_file, unprocessed_path, upload_cover
    from soundcloud.tagger import embed_tags
    from soundcloud.downloader import sanitize_m4a_streams
    import base64

    if not req.album_artist:
        req = req.model_copy(update={"album_artist": req.artist})
    if req.is_single and not req.album:
        req = req.model_copy(update={"album": f"{req.tracks[0].title} (Single)"})

    # Decode shared album cover
    shared_cover: Optional[bytes] = None
    if req.cover_art_b64:
        try:
            shared_cover = base64.b64decode(req.cover_art_b64)
        except Exception:
            pass

    saved = []
    for t in req.tracks:
        ext = os.path.splitext(t.temp_path)[1].lower() or ".mp3"
        fname = _track_filename(t, req.is_single, ext)
        remote_path = unprocessed_path(_safe(req.album_artist), _safe(req.album), fname)

        # Per-track cover takes priority over album cover
        cover: Optional[bytes] = shared_cover
        if t.cover_art_b64:
            try:
                cover = base64.b64decode(t.cover_art_b64)
            except Exception:
                pass

        meta = {
            "title": t.title,
            "artist": req.artist,
            "album_artist": req.album_artist,
            "album": req.album,
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

    # Upload cover.jpg into the album folder (use shared cover; fall back to
    # the first track's individual cover if there is no shared one)
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
            cover_bytes, _safe(req.album_artist), _safe(req.album)
        )
        if cover_path:
            saved.append(cover_path)
            logger.info("Uploaded cover.jpg → %s", cover_path)

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
# Download SoundCloud tracks, tag them, upload to SFTP unprocessed/
# ---------------------------------------------------------------------------


async def process_sc_album(req: ScProcessRequest) -> list[str]:
    """
    Download SoundCloud tracks, embed metadata + cover art, then upload to
      <SFTP_BASE>/unprocessed/<album_artist>/<album>/<filename>

    Also writes cover.jpg into the same folder when cover art is present.

    Returns the list of remote paths.
    """
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    from soundcloud.downloader import download_raw
    from soundcloud.tagger import embed_tags
    from services.sftp import upload_file, unprocessed_path, upload_cover

    _executor = ThreadPoolExecutor(max_workers=4)

    def _run_in_thread(fn, *args):
        loop = asyncio.get_event_loop()
        return loop.run_in_executor(_executor, fn, *args)

    if not req.album_artist:
        req = req.model_copy(update={"album_artist": req.artist})
    if req.is_single and not req.album:
        req = req.model_copy(update={"album": f"{req.tracks[0].title} (Single)"})

    # Decode shared album cover (used when a track has no individual cover)
    shared_cover: Optional[bytes] = None
    if req.cover_art_b64:
        try:
            shared_cover = base64.b64decode(req.cover_art_b64)
        except Exception:
            pass

    saved = []
    first_cover: Optional[bytes] = None  # fallback if no shared cover

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

        meta = {
            "title": t.title,
            "artist": t.artist or req.artist,
            "album_artist": req.album_artist,
            "album": req.album,
            "release_year": req.release_year,
            "track_number": t.track_number,
        }

        tmp_dir = tempfile.mkdtemp(prefix="sc_dl_")
        try:
            logger.info("Downloading SC track: %r", t.sc_url)
            raw_file = await _run_in_thread(download_raw, t.sc_url, tmp_dir)

            ext = os.path.splitext(raw_file)[1]
            fname = _track_filename(t, req.is_single, ext)
            remote_path = unprocessed_path(
                _safe(req.album_artist), _safe(req.album), fname
            )

            embed_tags(raw_file, meta, cover)

            logger.info("Uploading via SFTP: %s → %s", fname, remote_path)
            await _run_in_thread(upload_file, raw_file, remote_path)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        saved.append(remote_path)

    # Upload cover.jpg into the album folder once, after all tracks
    cover_bytes: Optional[bytes] = shared_cover or first_cover
    if cover_bytes:
        cover_path = await _run_in_thread(
            upload_cover, cover_bytes, _safe(req.album_artist), _safe(req.album)
        )
        if cover_path:
            saved.append(cover_path)
            logger.info("Uploaded cover.jpg → %s", cover_path)

    return saved
