import logging

import arq
import arq.jobs
from fastapi import APIRouter, HTTPException

from models import (
    BulkProcessRequest,
    JobStatus,
    ProcessRequest,
    ScProcessRequest,
)
from worker.settings import get_redis_settings

logger = logging.getLogger(__name__)
router = APIRouter()

_redis_pool: arq.connections.ArqRedis | None = None


async def get_redis() -> arq.connections.ArqRedis:
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = await arq.create_pool(get_redis_settings())
    return _redis_pool


async def close_redis() -> None:
    global _redis_pool
    if _redis_pool:
        await _redis_pool.aclose()
        _redis_pool = None


@router.post("/process", response_model=JobStatus, status_code=202)
async def process(req: ProcessRequest):
    """Enqueue album-processing job. Returns immediately; worker handles SFTP upload."""
    if not req.tracks:
        raise HTTPException(400, "No tracks provided")
    if not req.album and not req.is_single:
        raise HTTPException(400, "album is required for multi-track uploads")

    redis = await get_redis()
    job = await redis.enqueue_job("process_album_task", req.model_dump())
    logger.info("Enqueued process_album_task as job %s", job.job_id)
    return JobStatus(job_id=job.job_id, status="queued")


@router.post("/sc-process", response_model=JobStatus, status_code=202)
async def sc_process(req: ScProcessRequest):
    """Enqueue SoundCloud download+store job."""
    if not req.tracks:
        raise HTTPException(400, "No tracks provided")
    if not req.album and not req.is_single:
        raise HTTPException(400, "album is required")

    redis = await get_redis()
    job = await redis.enqueue_job("sc_process_task", req.model_dump())
    logger.info("Enqueued sc_process_task as job %s", job.job_id)
    return JobStatus(job_id=job.job_id, status="queued")


@router.post("/process-bulk", response_model=JobStatus, status_code=202)
async def process_bulk(req: BulkProcessRequest):
    """Enqueue bulk (multi-album) processing job."""
    if not req.albums:
        raise HTTPException(400, "No albums provided")

    redis = await get_redis()
    job = await redis.enqueue_job("process_bulk_task", req.model_dump())
    logger.info("Enqueued process_bulk_task as job %s", job.job_id)
    return JobStatus(job_id=job.job_id, status="queued")


@router.get("/jobs/{job_id}", response_model=JobStatus)
async def get_job_status(job_id: str):
    """Poll a job's status."""
    redis = await get_redis()
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
        arq.jobs.JobStatus.queued: "queued",
        arq.jobs.JobStatus.deferred: "queued",
        arq.jobs.JobStatus.in_progress: "in_progress",
    }
    return JobStatus(job_id=job_id, status=status_map.get(arq_status, "queued"))
