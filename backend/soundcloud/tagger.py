"""
Embed metadata and cover art into downloaded audio files.

Supports all formats SoundCloud/yt-dlp produces:
  .mp3          → ID3v2.3
  .ogg / .opus  → OggVorbis / OggOpus  (VorbisComment + METADATA_BLOCK_PICTURE)
  .flac         → FLAC                 (VorbisComment + pictures)
  .m4a / .mp4   → MP4Tags
"""

import base64
import logging
import struct
import urllib.request
import re
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Cover art fetch
# ---------------------------------------------------------------------------


def fetch_cover(artwork_url: Optional[str]) -> Optional[bytes]:
    """Download the highest-quality cover art from a URL."""
    if not artwork_url:
        return None
    # Request the t500x500 variant (best quality available without auth)
    url = re.sub(r"-(large|small|badge|tiny|crop)\b", "-t500x500", artwork_url)
    logger.info("Fetching cover art: %s", url)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.read()
    except Exception as exc:
        logger.warning("Could not fetch cover art: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Format-specific helpers
# ---------------------------------------------------------------------------


def _mime(data: bytes) -> str:
    return "image/png" if data[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"


def _vorbis_picture_block(cover: bytes) -> str:
    """
    Encode cover art as a base64 METADATA_BLOCK_PICTURE string,
    required for OGG/Opus/FLAC Vorbis-comment cover embedding.
    """
    mime = _mime(cover).encode()
    desc = b""
    # Picture type 3 = Front Cover
    block = (
        struct.pack(">I", 3)
        + struct.pack(">I", len(mime)) + mime
        + struct.pack(">I", len(desc)) + desc
        + struct.pack(">IIIII", 0, 0, 0, 0, len(cover))
        + cover
    )
    return base64.b64encode(block).decode()


def _embed_id3(path: str, meta: dict, cover: Optional[bytes]) -> None:
    from mutagen.id3 import (
        ID3, ID3NoHeaderError,
        TIT2, TPE1, TPE2, TALB, TDRC, TRCK, APIC,
    )
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()

    tags.clear()
    tags.add(TIT2(encoding=3, text=meta["title"]))
    tags.add(TPE1(encoding=3, text=meta["artist"]))
    tags.add(TPE2(encoding=3, text=meta["album_artist"]))
    tags.add(TALB(encoding=3, text=meta["album"]))
    tags.add(TDRC(encoding=3, text=str(meta["release_year"])))
    if meta.get("track_number") is not None:
        tags.add(TRCK(encoding=3, text=str(meta["track_number"])))
    if cover:
        tags.add(APIC(encoding=3, mime=_mime(cover), type=3, desc="Cover", data=cover))

    tags.save(path, v2_version=3)


def _embed_vorbis(path: str, meta: dict, cover: Optional[bytes], cls) -> None:
    """Generic Vorbis comment writer for OGG, Opus, FLAC."""
    audio = cls(path)
    if audio.tags is None:
        audio.add_tags()

    # Clear all existing Vorbis comments so junk fields from the source
    # (comment, description, encoder, www, contact, etc.) do not survive.
    audio.tags.clear()

    audio.tags["title"]       = meta["title"]
    audio.tags["artist"]      = meta["artist"]
    audio.tags["albumartist"] = meta["album_artist"]
    audio.tags["album"]       = meta["album"]
    audio.tags["date"]        = str(meta["release_year"])
    if meta.get("track_number") is not None:
        audio.tags["tracknumber"] = str(meta["track_number"])
    if cover:
        audio.tags["metadata_block_picture"] = [_vorbis_picture_block(cover)]

    audio.save()


def _embed_flac(path: str, meta: dict, cover: Optional[bytes]) -> None:
    from mutagen.flac import FLAC, Picture
    audio = FLAC(path)
    if audio.tags is None:
        audio.add_tags()

    # Clear all existing Vorbis comments first (junk fields from source).
    audio.tags.clear()

    audio.tags["title"]       = meta["title"]
    audio.tags["artist"]      = meta["artist"]
    audio.tags["albumartist"] = meta["album_artist"]
    audio.tags["album"]       = meta["album"]
    audio.tags["date"]        = str(meta["release_year"])
    if meta.get("track_number") is not None:
        audio.tags["tracknumber"] = str(meta["track_number"])

    if cover:
        pic = Picture()
        pic.type = 3  # Front Cover
        pic.mime = _mime(cover)
        pic.desc = "Cover"
        pic.data = cover
        audio.clear_pictures()
        audio.add_picture(pic)

    audio.save()


def _embed_mp4(path: str, meta: dict, cover: Optional[bytes]) -> None:
    from mutagen.mp4 import MP4, MP4Cover
    audio = MP4(path)
    if audio.tags is None:
        audio.add_tags()

    # Wipe everything so no source junk leaks into the output:
    # encoder strings (Lavf…), Telegram watermarks in comments,
    # container-level fields (major_brand, minor_version, compatible_brands),
    # or any other tag the original file or yt-dlp may have injected.
    audio.tags.clear()

    audio["\xa9nam"] = [meta["title"]]
    audio["\xa9ART"] = [meta["artist"]]
    audio["aART"]    = [meta["album_artist"]]
    audio["\xa9alb"] = [meta["album"]]
    audio["\xa9day"] = [str(meta["release_year"])]
    if meta.get("track_number") is not None:
        audio["trkn"] = [(int(meta["track_number"]), 0)]
    if cover:
        fmt = MP4Cover.FORMAT_PNG if _mime(cover) == "image/png" else MP4Cover.FORMAT_JPEG
        audio["covr"] = [MP4Cover(cover, imageformat=fmt)]

    audio.save()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def embed_tags(path: str, meta: dict, cover: Optional[bytes]) -> None:
    """
    Write metadata + cover art into *path*.

    *meta* dict keys:
        title, artist, album_artist, album, release_year,
        track_number (optional)

    Dispatches to the correct mutagen writer based on file extension.
    """
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""

    logger.info(
        "Tagging %s: title=%r artist=%r album=%r track=%s cover=%s",
        path, meta.get("title"), meta.get("artist"), meta.get("album"),
        meta.get("track_number"), f"{len(cover)} bytes" if cover else "none",
    )

    try:
        if ext == "mp3":
            _embed_id3(path, meta, cover)
        elif ext == "flac":
            _embed_flac(path, meta, cover)
        elif ext == "ogg":
            from mutagen.oggvorbis import OggVorbis
            _embed_vorbis(path, meta, cover, OggVorbis)
        elif ext == "opus":
            from mutagen.oggopus import OggOpus
            _embed_vorbis(path, meta, cover, OggOpus)
        elif ext in ("m4a", "mp4", "aac"):
            _embed_mp4(path, meta, cover)
        else:
            # Best-effort: let mutagen auto-detect
            from mutagen import File as MutagenFile
            audio = MutagenFile(path, easy=False)
            if audio is None:
                logger.warning("mutagen could not open %s — skipping tag write", path)
                return
            logger.warning("Unknown extension .%s — attempting generic mutagen write", ext)
            _embed_id3(path, meta, cover)  # last resort
    except Exception as exc:
        logger.error("Failed to embed tags into %s: %s", path, exc)
