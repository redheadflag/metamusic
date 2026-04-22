import io
import logging
import os
import tempfile
import zipfile

from fastapi import APIRouter, HTTPException, UploadFile

from models import AlbumMeta, TrackMeta
from processing import read_tags

logger = logging.getLogger(__name__)
router = APIRouter()

# Base directory for all uploads.
# In Docker: set UPLOAD_DIR=/app/uploads, mounted as a shared volume between
# backend and worker so the worker can read files the backend wrote.
# Falls back to /tmp/metamusic for local dev.
UPLOAD_BASE = os.getenv("UPLOAD_DIR", "/tmp/metamusic")


def _ensure_upload_dir() -> str:
    """Return the upload dir, creating it if it was wiped."""
    os.makedirs(UPLOAD_BASE, exist_ok=True)
    return UPLOAD_BASE


@router.post("/upload")
async def upload(files: list[UploadFile]):
    """Receive audio files, read their tags, return metadata for review."""
    if not files:
        raise HTTPException(400, "No files provided")

    upload_dir = _ensure_upload_dir()
    # Each upload batch gets its own subdir so concurrent requests don't collide
    batch_dir = tempfile.mkdtemp(prefix="batch_", dir=upload_dir)

    results = []
    for i, file in enumerate(files, 1):
        # Strip any path components the browser may include (Windows paths,
        # macOS folder prefixes, etc.) so we never try to write into a
        # nonexistent subdirectory.
        safe_name = os.path.basename((file.filename or f"track_{i}").replace("\\", "/"))
        tmp = os.path.join(batch_dir, f"{i:02d}_{safe_name}")
        content = await file.read()
        with open(tmp, "wb") as f:
            f.write(content)
        meta = read_tags(tmp, safe_name, i)
        logger.info(
            "Uploaded [%d/%d]: %r\n"
            "  title         = %r\n"
            "  artists       = %r\n"
            "  album_artists = %r\n"
            "  album         = %r\n"
            "  release_year  = %r\n"
            "  track_number  = %r\n"
            "  cover_art     = %s\n"
            "  temp_path     = %s",
            i,
            len(files),
            safe_name,
            meta.title,
            meta.artists,
            meta.album_artists,
            meta.album,
            meta.release_year,
            meta.track_number,
            f"{len(meta.cover_art_b64) * 3 // 4} bytes"
            if meta.cover_art_b64
            else "None",
            meta.temp_path,
        )
        results.append(meta)
    return results


@router.post("/upload-zip")
async def upload_zip(files: list[UploadFile]):
    """Receive zip archives, extract audio, return AlbumMeta list."""
    if not files:
        raise HTTPException(400, "No files provided")

    upload_dir = _ensure_upload_dir()

    albums: list[AlbumMeta] = []
    for zf in files:
        if not (zf.filename or "").lower().endswith(".zip"):
            raise HTTPException(400, f"'{zf.filename}' is not a zip file")

        content = await zf.read()
        album_dir = tempfile.mkdtemp(prefix="zip_", dir=upload_dir)

        with zipfile.ZipFile(io.BytesIO(content)) as z:
            audio_exts = {".mp3", ".flac", ".ogg", ".m4a", ".wav", ".aiff", ".aif"}
            members = sorted(
                m
                for m in z.namelist()
                if not m.startswith("__MACOSX")
                and os.path.splitext(m.lower())[1] in audio_exts
            )
            if not members:
                raise HTTPException(400, f"No audio files found in '{zf.filename}'")

            extracted = []
            for i, member in enumerate(members, 1):
                fname = os.path.basename(member)
                dest = os.path.join(album_dir, f"{i:02d}_{fname}")
                with z.open(member) as src, open(dest, "wb") as dst:
                    dst.write(src.read())
                extracted.append((i, fname, dest))

        tracks: list[TrackMeta] = []
        for i, fname, path in extracted:
            meta = read_tags(path, fname, i)
            logger.info(
                "zip %r track %d: title=%r artists=%r album=%r",
                zf.filename,
                i,
                meta.title,
                meta.artists,
                meta.album,
            )
            tracks.append(meta)

        first = tracks[0]
        albums.append(
            AlbumMeta(
                zip_name=zf.filename or "archive.zip",
                tracks=tracks,
                artists=list(first.artists),
                album_artists=list(first.album_artists or first.artists),
                album=first.album,
                release_year=first.release_year,
                cover_art_b64=first.cover_art_b64,
            )
        )
    return albums


@router.delete("/cancel")
async def cancel_tracks(body: dict):
    """Remove temp files for tracks the user excluded from batch processing."""
    import shutil

    temp_paths = body.get("temp_paths") or []
    removed = []
    for p in temp_paths:
        if not p:
            continue
        try:
            if os.path.isfile(p):
                os.unlink(p)
                removed.append(p)
            elif os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
                removed.append(p)
        except Exception as e:
            logger.warning("Could not remove %s: %s", p, e)
    logger.info("Cancelled %d temp path(s)", len(removed))
    return {"removed": removed}
