import os
import tempfile
import logging

from fastapi import FastAPI, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from models import ProcessRequest
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