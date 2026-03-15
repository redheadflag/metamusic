import io
import os
import tempfile
import logging

from fastapi import FastAPI, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from models import ProcessRequest, AlbumMeta, BulkProcessRequest, ScProcessRequest, TrackMeta, JobStatus
from processing import read_tags, process_album

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

from contextlib import asynccontextmanager
import arq
import arq.jobs
from arq.connections import ArqRedis
from worker.settings import get_redis_settings

_redis_pool: ArqRedis | None = None


async def _get_redis() -> ArqRedis:
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = await arq.create_pool(get_redis_settings())
    return _redis_pool


@asynccontextmanager
async def lifespan(app):
    from yt_sc_fetch.sc_api import SC_OAUTH_TOKEN
    if SC_OAUTH_TOKEN:
        logger.info("SoundCloud OAuth token loaded")
    else:
        logger.warning(
            "SC_OAUTH_TOKEN not set — SoundCloud fetch may fail for private/gated content."
        )
    await _get_redis()
    logger.info("ARQ Redis pool ready")
    yield
    if _redis_pool:
        await _redis_pool.aclose()


app = FastAPI(title="metamusic", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = tempfile.mkdtemp(prefix="metamusic_")


# ---------------------------------------------------------------------------
# Upload endpoints (unchanged)
# ---------------------------------------------------------------------------

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
            meta.title, meta.artist, meta.album_artist, meta.album,
            meta.release_year, meta.track_number,
            f"{len(meta.cover_art_b64) * 3 // 4} bytes" if meta.cover_art_b64 else "None",
            meta.temp_path,
        )
        results.append(meta)
    return results


@app.post("/api/upload-zip")
async def upload_zip(files: list[UploadFile]):
    """Receive zip archives, extract audio, return AlbumMeta list."""
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


# ---------------------------------------------------------------------------
# Process endpoints — enqueue jobs, return 202 + job_id
# ---------------------------------------------------------------------------

@app.post("/api/process", response_model=JobStatus, status_code=202)
async def process(req: ProcessRequest):
    """Enqueue album-processing job. Poll GET /api/jobs/{job_id} for result."""
    if not req.tracks:
        raise HTTPException(400, "No tracks provided")
    if not req.album and not req.is_single:
        raise HTTPException(400, "album is required for multi-track uploads")

    redis = await _get_redis()
    job = await redis.enqueue_job("process_album_task", req.model_dump())
    logger.info("Enqueued process_album_task as job %s", job.job_id)
    return JobStatus(job_id=job.job_id, status="queued")


@app.post("/api/sc-process", response_model=JobStatus, status_code=202)
async def sc_process(req: ScProcessRequest):
    """Enqueue SoundCloud download+store job."""
    if not req.tracks:
        raise HTTPException(400, "No tracks provided")
    if not req.album and not req.is_single:
        raise HTTPException(400, "album is required")

    redis = await _get_redis()
    job = await redis.enqueue_job("sc_process_task", req.model_dump())
    logger.info("Enqueued sc_process_task as job %s", job.job_id)
    return JobStatus(job_id=job.job_id, status="queued")


@app.post("/api/process-bulk", response_model=JobStatus, status_code=202)
async def process_bulk(req: BulkProcessRequest):
    """Enqueue bulk (multi-album) processing job."""
    if not req.albums:
        raise HTTPException(400, "No albums provided")

    redis = await _get_redis()
    job = await redis.enqueue_job("process_bulk_task", req.model_dump())
    logger.info("Enqueued process_bulk_task as job %s", job.job_id)
    return JobStatus(job_id=job.job_id, status="queued")


# ---------------------------------------------------------------------------
# Job status polling
# ---------------------------------------------------------------------------

@app.get("/api/jobs/{job_id}", response_model=JobStatus)
async def get_job_status(job_id: str):
    """
    Poll a job's status.

    statuses:
      queued       — waiting in queue
      in_progress  — worker is running it
      complete     — finished; `result` holds the output
      failed       — task raised an exception; `error` holds the message
      not_found    — unknown / expired job_id
    """
    redis = await _get_redis()
    job = arq.jobs.Job(job_id, redis)
    info = await job.info()

    if info is None:
        return JobStatus(job_id=job_id, status="not_found")

    arq_status = await job.status()

    if arq_status == arq.jobs.JobStatus.complete:
        try:
            result = await job.result(timeout=0)
            return JobStatus(job_id=job_id, status="complete", result=result)
        except Exception as exc:
            return JobStatus(job_id=job_id, status="failed", error=str(exc))

    if arq_status == arq.jobs.JobStatus.not_found:
        return JobStatus(job_id=job_id, status="not_found")

    status_map = {
        arq.jobs.JobStatus.queued:      "queued",
        arq.jobs.JobStatus.deferred:    "queued",
        arq.jobs.JobStatus.in_progress: "in_progress",
    }
    return JobStatus(job_id=job_id, status=status_map.get(arq_status, "queued"))


# ---------------------------------------------------------------------------
# SoundCloud metadata-fetch endpoints (fast, no queue)
# ---------------------------------------------------------------------------

from concurrent.futures import ThreadPoolExecutor
import asyncio

_executor = ThreadPoolExecutor(max_workers=4)


def _run_blocking(fn, *args):
    loop = asyncio.get_event_loop()
    return loop.run_in_executor(_executor, fn, *args)


@app.post("/api/sc-fetch")
async def sc_fetch(body: dict):
    """Fetch metadata from a SoundCloud URL via SC API v2."""
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
        logger.info("SC entry %d: title=%r artist=%r album=%r url=%s",
                    i, t.title, t.artist, t.album, t.sc_url)
    return results


async def process_sc_album(req) -> list[str]:
    """
    Download SoundCloud tracks in their best available audio quality and store
    them raw (no FFmpeg) into MUSIC_LIBRARY_PATH.

    The standalone processor service is responsible for converting and tagging
    these files on the more powerful machine.
    """
    import shutil
    import tempfile as tf
    from processing import _safe, _find_ci, MUSIC_LIBRARY_PATH

    is_single = getattr(req, "is_single", False)

    if not req.album_artist:
        req = req.model_copy(update={"album_artist": req.artist})
    if is_single and not req.album:
        req = req.model_copy(update={"album": f"{req.tracks[0].title} (Single)"})

    saved = []
    for t in req.tracks:
        if not t.sc_url:
            raise ValueError(f"Missing sc_url for track '{t.title}'")

        track_num = t.track_number
        album = req.album

        artist_dir = _find_ci(MUSIC_LIBRARY_PATH, _safe(req.album_artist))
        out_dir    = _find_ci(artist_dir, _safe(album))
        os.makedirs(out_dir, exist_ok=True)

        # Destination filename keeps the raw extension (filled in after download)
        base_name = (
            _safe(t.title) if is_single
            else _safe(f"{track_num:02d} {t.title}")
        )

        def _download_raw(sc_url, tmp_dir):
            """Download best audio to tmp_dir, return the produced file path."""
            from yt_sc_fetch.utils import run as yt_run
            from yt_sc_fetch.sc import _ytdlp_base
            output_tmpl = os.path.join(tmp_dir, "%(id)s.%(ext)s")
            result = yt_run(_ytdlp_base() + [
                "--no-playlist",
                "--format", "bestaudio/best",
                # No --extract-audio / --audio-format: keep the native format
                "--no-embed-metadata", "--no-embed-thumbnail",
                "--output", output_tmpl,
                sc_url,
            ])
            if result.returncode != 0:
                raise RuntimeError(f"yt-dlp failed: {result.stderr[-500:]}")
            files = os.listdir(tmp_dir)
            if not files:
                raise RuntimeError("yt-dlp produced no file")
            return os.path.join(tmp_dir, files[0])

        logger.info("Downloading SC track (raw): %r → %s/", t.sc_url, out_dir)
        tmp_dir = tf.mkdtemp(prefix="sc_dl_")
        try:
            raw_file = await _run_blocking(_download_raw, t.sc_url, tmp_dir)
            ext = os.path.splitext(raw_file)[1]
            dest = _find_ci(out_dir, base_name + ext)
            shutil.move(raw_file, dest)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        saved.append(dest)

    return saved


@app.post("/api/sc-fetch-artist")
async def sc_fetch_artist(body: dict):
    """Fetch all albums for a SoundCloud artist profile URL."""
    from yt_sc_fetch.sc_api import resolve_artist

    url = (body.get("url") or "").strip()
    if not url:
        raise HTTPException(400, "url is required")

    logger.info("SC artist fetch: %s", url)
    try:
        albums = await _run_blocking(resolve_artist, url)
    except Exception as e:
        logger.error("SC artist API error: %s", e)
        raise HTTPException(400, str(e))

    logger.info("SC artist: %d album(s) found", len(albums))
    return albums


@app.delete("/api/cancel")
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
