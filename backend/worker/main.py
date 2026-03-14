"""
ARQ task functions.

Each function receives `ctx` (the ARQ job context) as the first argument,
followed by the serialised request data.  Tasks run inside the ARQ worker
process and therefore have full access to processing.py / yt_sc_fetch, etc.

Heavy work is kept in the existing helpers so this file stays thin.
"""

import logging
import os

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# task: process_album_task
# Corresponds to POST /api/process
# ---------------------------------------------------------------------------

async def process_album_task(ctx, req_dict: dict) -> dict:
    """
    Embed metadata and save uploaded tracks to the music library.
    `req_dict` is a plain dict representation of ProcessRequest.
    """
    from models import ProcessRequest
    from processing import process_album

    req = ProcessRequest(**req_dict)

    # Mirror the logic that was inline in the endpoint
    if not req.album_artist:
        req = req.model_copy(update={"album_artist": req.artist})

    if req.is_single and not req.album:
        req = req.model_copy(update={"album": f"{req.tracks[0].title} (Single)"})

    logger.info(
        "[job %s] process_album_task: artist=%r album=%r tracks=%d",
        ctx["job_id"], req.artist, req.album, len(req.tracks),
    )

    saved = process_album(req)
    logger.info("[job %s] saved: %s", ctx["job_id"], saved)
    return {"saved": saved}


# ---------------------------------------------------------------------------
# task: sc_process_task
# Corresponds to POST /api/sc-process
# ---------------------------------------------------------------------------

async def sc_process_task(ctx, req_dict: dict) -> dict:
    """
    Download SoundCloud tracks, convert to MP3, embed confirmed metadata.
    `req_dict` is a plain dict representation of ScProcessRequest.
    """
    from models import ScProcessRequest
    from main import _process_sc_album   # shared helper lives in main.py

    req = ScProcessRequest(**req_dict)

    logger.info(
        "[job %s] sc_process_task: artist=%r album=%r tracks=%d",
        ctx["job_id"], req.artist, req.album, len(req.tracks),
    )

    saved = await _process_sc_album(req)
    logger.info("[job %s] SC saved: %s", ctx["job_id"], saved)
    return {"saved": saved}


# ---------------------------------------------------------------------------
# task: process_bulk_task
# Corresponds to POST /api/process-bulk
# ---------------------------------------------------------------------------

async def process_bulk_task(ctx, req_dict: dict) -> dict:
    """
    Process multiple albums in one job (e.g. from zip uploads).
    `req_dict` is a plain dict representation of BulkProcessRequest.
    """
    from models import BulkProcessRequest, ProcessRequest
    from processing import process_album
    from main import _process_sc_album

    req = BulkProcessRequest(**req_dict)

    logger.info(
        "[job %s] process_bulk_task: %d album(s)",
        ctx["job_id"], len(req.albums),
    )

    all_saved: list[str] = []
    for album_req in req.albums:
        if not album_req.album_artist:
            album_req = album_req.model_copy(update={"album_artist": album_req.artist})
        if not album_req.album:
            raise ValueError("album is required for each entry")

        is_sc = any(t.sc_url for t in album_req.tracks)
        if is_sc:
            saved = await _process_sc_album(album_req)
        else:
            saved = process_album(album_req)

        all_saved.extend(saved)

    logger.info("[job %s] bulk saved: %d file(s)", ctx["job_id"], len(all_saved))
    return {"saved": all_saved}


# ---------------------------------------------------------------------------
# WorkerSettings — picked up by `arq worker.main.WorkerSettings`
# ---------------------------------------------------------------------------

from worker.settings import get_redis_settings   # noqa: E402  (after task defs)


class WorkerSettings:
    """ARQ worker configuration loaded by `arq worker.main.WorkerSettings`."""

    functions = [
        process_album_task,
        sc_process_task,
        process_bulk_task,
    ]

    redis_settings = get_redis_settings()

    # Retry failed jobs once before giving up
    max_tries = 2
    max_jobs = 1

    # How long a single job may run (seconds).
    # SC downloads can be slow, so give 30 minutes.
    job_timeout = 1800

    on_startup = None
    on_shutdown = None
