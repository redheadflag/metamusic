import base64
import logging
import os
import re
from typing import Optional

from models import TrackMeta, ProcessRequest

logger = logging.getLogger(__name__)

OUTPUT_DIR = "/music"


def _safe(s: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "_", s).strip()


def _normalize_artists(artist: str, title: str) -> tuple[str, str]:
    """
    Split multiple artists into a single album_artist + (feat. ...) in the title.
    e.g. artist="Gone.Fludd, ЛСП" title="Ути-Пути"
      -> artist="Gone.Fludd"  title="Ути-Пути (feat. ЛСП)"
    """
    parts = [a.strip() for a in re.split(r"[,&/;\\]", artist) if a.strip()]
    if len(parts) <= 1:
        return artist, title

    main      = parts[0]
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

        # FLAC cover art lives in audio.pictures, not in tags
        cover_art_b64 = None
        pictures = getattr(audio, "pictures", [])
        if pictures:
            cover_art_b64 = base64.b64encode(pictures[0].data).decode()

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
# Embed tags and save to OUTPUT_DIR
# ---------------------------------------------------------------------------

def _source_bitrate(path: str) -> int:
    """Return audio bitrate in kbps using ffprobe, or 0 on failure."""
    import subprocess, json
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-print_format", "json",
                "-show_streams", "-select_streams", "a:0",
                path,
            ],
            capture_output=True, text=True, timeout=15,
        )
        streams = json.loads(result.stdout).get("streams", [])
        if streams:
            return int(streams[0].get("bit_rate", 0)) // 1000
    except Exception:
        pass
    return 0


def _to_mp3(src: str, dest: str, meta: dict, cover_bytes: Optional[bytes]) -> None:
    """
    Convert *src* to MP3 at ≤256 kbps and embed metadata via ffmpeg.
    If the source is already MP3 at ≤256 kbps the audio stream is copied
    without re-encoding to avoid generation loss.
    """
    import subprocess, tempfile

    src_kbps  = _source_bitrate(src)
    is_mp3    = src.lower().endswith(".mp3")
    target_br = min(src_kbps, 256) if src_kbps > 0 else 256

    # Stream-copy only when already MP3 and within limit
    if is_mp3 and src_kbps <= 256:
        audio_opts = ["-c:a", "copy"]
    else:
        audio_opts = ["-c:a", "libmp3lame", "-b:a", f"{target_br}k", "-q:a", "0"]

    cmd = ["ffmpeg", "-y", "-i", src]

    # Attach cover art as a second input if available
    if cover_bytes:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            tmp.write(cover_bytes)
            cover_path = tmp.name
        cmd += ["-i", cover_path]
        map_opts   = ["-map", "0:a", "-map", "1:v"]
        cover_opts = ["-c:v", "mjpeg", "-disposition:v", "attached_pic"]
    else:
        cover_path = None
        map_opts   = ["-map", "0:a"]
        cover_opts = []

    cmd += map_opts + audio_opts + cover_opts + [
        "-id3v2_version", "3",
        "-metadata", f"title={meta['title']}",
        "-metadata", f"artist={meta['artist']}",
        "-metadata", f"album_artist={meta['album_artist']}",
        "-metadata", f"album={meta['album']}",
        "-metadata", f"date={meta['release_year']}",
        *([] if meta['track_number'] is None else ["-metadata", f"track={meta['track_number']}"]),
        dest,
    ]

    logger.info(
        "ffmpeg: %s → %s (%s, %d kbps → %d kbps)",
        os.path.basename(src), os.path.basename(dest),
        "copy" if is_mp3 and src_kbps <= 256 else "encode",
        src_kbps, target_br,
    )

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

    if cover_path:
        os.unlink(cover_path)

    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed:\n{result.stderr[-1000:]}")


def process_album(req: ProcessRequest) -> list[str]:
    """
    Convert every track to MP3 (≤256 kbps), embed metadata, save to OUTPUT_DIR.
    Single track uploads get album = "<title> (Single)" and no track number prefix.
    """
    is_single = req.is_single

    cover_bytes: Optional[bytes] = None
    if req.cover_art_b64:
        cover_bytes = base64.b64decode(req.cover_art_b64)

    saved = []
    for t in req.tracks:
        art = cover_bytes
        if art is None and t.cover_art_b64:
            art = base64.b64decode(t.cover_art_b64)

        album = req.album

        meta = {
            "title":        t.title,
            "artist":       req.artist,
            "album_artist": req.album_artist,
            "album":        album,
            "release_year": req.release_year,
            "track_number": None if is_single else t.track_number,
        }

        out_dir = os.path.join(
            OUTPUT_DIR,
            _safe(req.album_artist),
            _safe(album),
        )
        os.makedirs(out_dir, exist_ok=True)

        fname = _safe(t.title) + ".mp3"  if is_single else _safe(f"{t.track_number:02d} {t.title}") + ".mp3"
        dest  = os.path.join(out_dir, fname)

        _to_mp3(t.temp_path, dest, meta, art)
        os.unlink(t.temp_path)
        saved.append(dest)

    return saved