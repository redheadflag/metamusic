import io
import os
import tempfile
import logging

from fastapi import FastAPI, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from models import ProcessRequest, AlbumMeta, BulkProcessRequest, TrackMeta
from processing import read_tags, process_album

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(app):
    from yt_sc_fetch.sc_api import SC_OAUTH_TOKEN

    if SC_OAUTH_TOKEN:
        logger.info("SoundCloud credentials loaded")
    else:
        logger.warning(
            "SC_CLIENT_ID or SC_OAUTH_TOKEN not set — SoundCloud fetch will fail. "
            "Get them from browser devtools on soundcloud.com."
        )
    yield


app = FastAPI(title="metamusic", lifespan=lifespan)

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
            i,
            len(files),
            file.filename,
            meta.title,
            meta.artist,
            meta.album_artist,
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
        len(req.tracks),
        req.artist,
        req.album,
        req.release_year,
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
                (
                    m
                    for m in z.namelist()
                    if not m.startswith("__MACOSX")
                    and os.path.splitext(m.lower())[1] in audio_exts
                ),
                key=lambda n: n,
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

        tracks = []
        for i, fname, path in extracted:
            meta = read_tags(path, fname, i)
            logger.info(
                "zip %r track %d: title=%r artist=%r album=%r",
                zf.filename,
                i,
                meta.title,
                meta.artist,
                meta.album,
            )
            tracks.append(meta)

        first = tracks[0]
        albums.append(
            AlbumMeta(
                zip_name=zf.filename or "archive.zip",
                tracks=tracks,
                artist=first.artist,
                album_artist=first.album_artist or first.artist,
                album=first.album,
                release_year=first.release_year,
                cover_art_b64=first.cover_art_b64,
            )
        )

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

        logger.info(
            "Bulk processing: artist=%r album=%r tracks=%d",
            album_req.artist,
            album_req.album,
            len(album_req.tracks),
        )
        saved = process_album(album_req)
        all_saved.extend(saved)

    return {"saved": all_saved}


# ---------------------------------------------------------------------------
# SoundCloud endpoints
# ---------------------------------------------------------------------------

from models import ScProcessRequest
from concurrent.futures import ThreadPoolExecutor
import asyncio

_executor = ThreadPoolExecutor(max_workers=4)


def _run_blocking(fn, *args):
    """Run a blocking function in a thread pool."""
    loop = asyncio.get_event_loop()
    return loop.run_in_executor(_executor, fn, *args)


@app.post("/api/sc-fetch")
async def sc_fetch(body: dict):
    """
    Fetch metadata from a SoundCloud URL using the SC API v2.
    Returns TrackMeta list pre-filled from API response.
    """
    from yt_sc_fetch.sc_api import resolve_url

    url = (body.get("url") or "").strip()
    if not url:
        raise HTTPException(400, "url is required")

    logger.info("SC fetch: %s", url)

    try:
        tracks = await _run_blocking(resolve_url, url)
    except Exception as e:
        logger.error("SC API error: %s", e)
        raise HTTPException(400, str(e))

    results = [TrackMeta(**t) for t in tracks]
    for i, t in enumerate(results, 1):
        logger.info(
            "SC entry %d: title=%r artist=%r album=%r url=%s",
            i,
            t.title,
            t.artist,
            t.album,
            t.sc_url,
        )
    return results


@app.post("/api/sc-process")
async def sc_process(req: ScProcessRequest):
    """
    Download SoundCloud tracks, convert to MP3, embed confirmed metadata.
    """
    import base64
    import tempfile as tf
    from processing import _to_mp3, _safe, MUSIC_LIBRARY_PATH

    if not req.tracks:
        raise HTTPException(400, "No tracks provided")

    is_single = req.is_single

    if not req.album_artist:
        req = req.model_copy(update={"album_artist": req.artist})

    if is_single and not req.album:
        req = req.model_copy(update={"album": f"{req.tracks[0].title} (Single)"})

    if not req.album:
        raise HTTPException(400, "album is required")

    cover_bytes: bytes | None = None
    if req.cover_art_b64:
        cover_bytes = base64.b64decode(req.cover_art_b64)

    saved = []
    for t in req.tracks:
        if not t.sc_url:
            raise HTTPException(400, f"Missing sc_url for track '{t.title}'")

        art = cover_bytes or (
            base64.b64decode(t.cover_art_b64) if t.cover_art_b64 else None
        )

        track_num = t.track_number
        album = req.album

        meta = {
            "title": t.title,
            "artist": req.artist,
            "album_artist": req.album_artist,
            "album": album,
            "release_year": req.release_year,
            "track_number": None if is_single else track_num,
        }

        out_dir = os.path.join(
            MUSIC_LIBRARY_PATH, _safe(req.album_artist), _safe(album)
        )
        os.makedirs(out_dir, exist_ok=True)

        fname = (
            _safe(t.title) + ".mp3"
            if is_single
            else _safe(f"{track_num:02d} {t.title}") + ".mp3"
        )
        dest = os.path.join(out_dir, fname)

        logger.info("Downloading SC track: %r → %s", t.sc_url, dest)

        def _download_and_convert(sc_url, tmp_dir, dest, meta, art):
            from yt_sc_fetch.utils import run as yt_run

            output_tmpl = os.path.join(tmp_dir, "%(id)s.%(ext)s")
            result = yt_run(
                [
                    "yt-dlp",
                    "--no-playlist",
                    "--format",
                    "bestaudio/best",
                    "--extract-audio",
                    "--audio-format",
                    "mp3",
                    "--audio-quality",
                    "0",
                    "--no-embed-metadata",
                    "--no-embed-thumbnail",
                    "--output",
                    output_tmpl,
                    sc_url,
                ]
            )
            if result.returncode != 0:
                raise RuntimeError(f"yt-dlp failed: {result.stderr[-500:]}")
            mp3 = next(
                (
                    os.path.join(tmp_dir, f)
                    for f in os.listdir(tmp_dir)
                    if f.endswith(".mp3")
                ),
                None,
            )
            if not mp3:
                raise RuntimeError("yt-dlp produced no mp3 file")
            _to_mp3(mp3, dest, meta, art)
            os.unlink(mp3)

        tmp_dir = tf.mkdtemp(prefix="sc_dl_")
        try:
            await _run_blocking(
                _download_and_convert, t.sc_url, tmp_dir, dest, meta, art
            )
        finally:
            import shutil

            shutil.rmtree(tmp_dir, ignore_errors=True)

        saved.append(dest)

    logger.info("SC saved: %s", saved)
    return {"saved": saved}
