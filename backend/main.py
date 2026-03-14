import io
import os
import tempfile
import logging

from fastapi import FastAPI, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from models import ProcessRequest, AlbumMeta, BulkProcessRequest
from processing import read_tags, process_album

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="metamusic")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = tempfile.mkdtemp(prefix="metamusic_")


@app.post("/api/upload")
async def upload(files: list[UploadFile]):
    """Receive audio files, read their tags, return metadata for review."""
    if not files:
        raise HTTPException(400, "No files provided")

    results = []
    for i, file in enumerate(files, 1):
        tmp = os.path.join(UPLOAD_DIR, f"{i:02d}_{file.filename}")
        content = await file.read()
        with open(tmp, "wb") as f:
            f.write(content)
        meta = read_tags(tmp, file.filename or f"track_{i}.mp3", i)
        logger.info(
            "Uploaded [%d/%d]: %r\n"
            "  title        = %r\n"
            "  artist       = %r\n"
            "  album_artist = %r\n"
            "  album        = %r\n"
            "  release_year = %r\n"
            "  track_number = %r\n"
            "  cover_art    = %s\n"
            "  temp_path    = %s",
            i, len(files), file.filename,
            meta.title,
            meta.artist,
            meta.album_artist,
            meta.album,
            meta.release_year,
            meta.track_number,
            f"{len(meta.cover_art_b64) * 3 // 4} bytes" if meta.cover_art_b64 else "None",
            meta.temp_path,
        )
        results.append(meta)

    return results


@app.post("/api/process")
async def process(req: ProcessRequest):
    """Embed confirmed metadata and save files to the music library."""
    if not req.tracks:
        raise HTTPException(400, "No tracks provided")

    is_single = req.is_single

    # Auto-fill album_artist from artist if missing
    if not req.album_artist:
        req = req.model_copy(update={"album_artist": req.artist})

    # Singles: derive album name from track title
    if is_single and not req.album:
        req = req.model_copy(update={"album": f"{req.tracks[0].title} (Single)"})

    if not req.album:
        raise HTTPException(400, "album is required for multi-track uploads")

    logger.info(
        "Processing %d track(s): artist=%r album=%r year=%r",
        len(req.tracks), req.artist, req.album, req.release_year,
    )
    saved = process_album(req)
    logger.info("Saved: %s", saved)
    return {"saved": saved}

@app.post("/api/upload-zip")
async def upload_zip(files: list[UploadFile]):
    """
    Receive one or more zip archives, extract audio files from each,
    read their tags, and return a list of AlbumMeta (one per zip).
    """
    import zipfile

    if not files:
        raise HTTPException(400, "No files provided")

    albums: list[AlbumMeta] = []

    for zf in files:
        if not (zf.filename or "").lower().endswith(".zip"):
            raise HTTPException(400, f"'{zf.filename}' is not a zip file")

        content = await zf.read()
        album_dir = tempfile.mkdtemp(prefix="metamusic_zip_", dir=UPLOAD_DIR)

        with zipfile.ZipFile(io.BytesIO(content)) as z:
            audio_exts = {".mp3", ".flac", ".ogg", ".m4a", ".wav", ".aiff", ".aif"}
            members = sorted(
                (m for m in z.namelist()
                 if not m.startswith("__MACOSX") and
                    os.path.splitext(m.lower())[1] in audio_exts),
                key=lambda n: n
            )
            if not members:
                raise HTTPException(400, f"No audio files found in '{zf.filename}'")

            extracted = []
            for i, member in enumerate(members, 1):
                fname = os.path.basename(member)
                dest  = os.path.join(album_dir, f"{i:02d}_{fname}")
                with z.open(member) as src, open(dest, "wb") as dst:
                    dst.write(src.read())
                extracted.append((i, fname, dest))

        tracks = []
        for i, fname, path in extracted:
            meta = read_tags(path, fname, i)
            logger.info("zip %r track %d: title=%r artist=%r album=%r",
                        zf.filename, i, meta.title, meta.artist, meta.album)
            tracks.append(meta)

        first = tracks[0]
        albums.append(AlbumMeta(
            zip_name=zf.filename or "archive.zip",
            tracks=tracks,
            artist=first.artist,
            album_artist=first.album_artist or first.artist,
            album=first.album,
            release_year=first.release_year,
            cover_art_b64=first.cover_art_b64,
        ))

    return albums


@app.post("/api/process-bulk")
async def process_bulk(req: BulkProcessRequest):
    """Process multiple albums at once (e.g. from zip uploads)."""
    if not req.albums:
        raise HTTPException(400, "No albums provided")

    all_saved = []
    for album_req in req.albums:
        if not album_req.album_artist:
            album_req = album_req.model_copy(update={"album_artist": album_req.artist})
        if not album_req.album:
            raise HTTPException(400, "album is required for each entry")

        logger.info("Bulk processing: artist=%r album=%r tracks=%d",
                    album_req.artist, album_req.album, len(album_req.tracks))
        saved = process_album(album_req)
        all_saved.extend(saved)

    return {"saved": all_saved}
