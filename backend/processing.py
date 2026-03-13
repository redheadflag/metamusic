import base64
import os
import re
import shutil
from typing import Optional

from models import TrackMeta, ProcessRequest

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

def process_album(req: ProcessRequest) -> list[str]:
    """
    Embed metadata into every track and move to OUTPUT_DIR.
    Preserves original format — re-tags in place, then moves.
    """
    from mutagen import File as MutagenFile
    from mutagen.id3 import (
        ID3, ID3NoHeaderError,
        TPE1, TPE2, TALB, TIT2, TDRC, TRCK, APIC,
    )
    from mutagen.flac import Picture
    import struct

    cover_bytes: Optional[bytes] = None
    if req.cover_art_b64:
        cover_bytes = base64.b64decode(req.cover_art_b64)

    out_dir = os.path.join(
        OUTPUT_DIR,
        _safe(req.album_artist),
        _safe(req.album),
    )
    os.makedirs(out_dir, exist_ok=True)

    saved = []
    for t in req.tracks:
        art = cover_bytes
        if art is None and t.cover_art_b64:
            art = base64.b64decode(t.cover_art_b64)

        audio = MutagenFile(t.temp_path, easy=False)
        is_id3 = audio is not None and hasattr(audio.tags, "getall")

        if is_id3:
            try:
                tags = ID3(t.temp_path)
            except ID3NoHeaderError:
                tags = ID3()
            tags.clear()
            tags.add(TIT2(encoding=3, text=t.title))
            tags.add(TPE1(encoding=3, text=req.artist))
            tags.add(TPE2(encoding=3, text=req.album_artist))
            tags.add(TALB(encoding=3, text=req.album))
            tags.add(TDRC(encoding=3, text=req.release_year))
            tags.add(TRCK(encoding=3, text=str(t.track_number)))
            if art:
                mime = "image/png" if art[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"
                tags.add(APIC(encoding=3, mime=mime, type=3, desc="Cover", data=art))
            tags.save(t.temp_path, v2_version=3)

        else:
            # Vorbis comment (FLAC, OGG…)
            if audio.tags is None:
                audio.add_tags()
            audio.tags["title"]       = [t.title]
            audio.tags["artist"]      = [req.artist]
            audio.tags["albumartist"] = [req.album_artist]
            audio.tags["album"]       = [req.album]
            audio.tags["date"]        = [req.release_year]
            audio.tags["tracknumber"] = [str(t.track_number)]

            if art and hasattr(audio, "clear_pictures"):
                from mutagen.flac import Picture
                pic = Picture()
                pic.type = 3
                pic.mime = "image/png" if art[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"
                pic.data = art
                audio.clear_pictures()
                audio.add_picture(pic)

            audio.save()

        ext  = os.path.splitext(t.file_name)[1] or ".mp3"
        fname = _safe(f"{t.track_number:02d} {t.title}") + ext
        dest  = os.path.join(out_dir, fname)
        shutil.move(t.temp_path, dest)
        saved.append(dest)

    return saved