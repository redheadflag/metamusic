"""
ARQ task functions.

Each function receives `ctx` (the ARQ job context) as the first argument,
followed by the serialised request data.  Tasks run inside the ARQ worker
process and have full access to processing.py / soundcloud/, etc.

Tasks copy / download raw audio files into MUSIC_LIBRARY_PATH.
The standalone processor service performs conversion + metadata embedding.
"""

import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# task: process_album_task  (POST /api/process)
# ---------------------------------------------------------------------------


async def process_album_task(ctx, req_dict: dict) -> dict:
    """Copy uploaded tracks (raw) to MUSIC_LIBRARY_PATH."""
    from models import ProcessRequest
    from processing import process_album

    req = ProcessRequest(**req_dict)

    if not req.album_artist:
        req = req.model_copy(update={"album_artist": req.artist})
    if req.is_single and not req.album:
        req = req.model_copy(update={"album": f"{req.tracks[0].title} (Single)"})

    logger.info(
        "[job %s] process_album_task: artist=%r album=%r tracks=%d",
        ctx["job_id"], req.artist, req.album, len(req.tracks),
    )

    saved = process_album(req)
    logger.info("[job %s] stored (raw): %s", ctx["job_id"], saved)
    return {"saved": saved}


# ---------------------------------------------------------------------------
# task: sc_process_task  (POST /api/sc-process)
# ---------------------------------------------------------------------------


async def sc_process_task(ctx, req_dict: dict) -> dict:
    """Download SoundCloud tracks in native format and store raw."""
    from models import ScProcessRequest
    from processing import process_sc_album

    req = ScProcessRequest(**req_dict)

    logger.info(
        "[job %s] sc_process_task: artist=%r album=%r tracks=%d",
        ctx["job_id"], req.artist, req.album, len(req.tracks),
    )

    saved = await process_sc_album(req)
    logger.info("[job %s] SC stored (raw): %s", ctx["job_id"], saved)
    return {"saved": saved}


# ---------------------------------------------------------------------------
# task: process_bulk_task  (POST /api/process-bulk)
# ---------------------------------------------------------------------------


async def process_bulk_task(ctx, req_dict: dict) -> dict:
    """Store multiple albums' raw files in one job (e.g. from zip uploads)."""
    from models import BulkProcessRequest
    from processing import process_album, process_sc_album

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

        if any(t.sc_url for t in album_req.tracks):
            saved = await process_sc_album(album_req)
        else:
            saved = process_album(album_req)

        all_saved.extend(saved)

    logger.info("[job %s] bulk stored (raw): %d file(s)", ctx["job_id"], len(all_saved))
    return {"saved": all_saved}


# ---------------------------------------------------------------------------
# WorkerSettings — picked up by `arq worker.main.WorkerSettings`
# ---------------------------------------------------------------------------

from worker.settings import get_redis_settings  # noqa: E402


class WorkerSettings:
    """ARQ worker configuration."""

    functions = [
        process_album_task,
        sc_process_task,
        process_bulk_task,
    ]

    redis_settings = get_redis_settings()

    max_tries = 2
    max_jobs = 1
    job_timeout = 3600
