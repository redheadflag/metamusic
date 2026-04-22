"""
API endpoints for YouTube playlist import.

POST /api/yt-scan    — fetch playlist tracks + check Navidrome for each
POST /api/yt-import  — enqueue download/upload job for unmatched tracks
"""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, HTTPException

from models import JobStatus, YtImportRequest, YtPlaylistScan, YtTrackScan

logger = logging.getLogger(__name__)
router = APIRouter()

_executor = ThreadPoolExecutor(max_workers=4)


def _run_blocking(fn, *args):
    loop = asyncio.get_event_loop()
    return loop.run_in_executor(_executor, fn, *args)


@router.post("/yt-scan", response_model=YtPlaylistScan)
async def yt_scan(body: dict):
    """
    Fetch a YouTube playlist and check each track against the Navidrome library.
    Returns the playlist name and a list of tracks with match status.
    """
    from youtube.matcher import find_in_navidrome
    from youtube.playlist import fetch_playlist

    url = (body.get("url") or "").strip()
    if not url:
        raise HTTPException(400, "url is required")

    logger.info("YT scan requested: %s", url)

    try:
        playlist = await _run_blocking(fetch_playlist, url)
    except Exception as exc:
        logger.error("YT playlist fetch error: %s", exc)
        raise HTTPException(400, str(exc))

    # Match each track against Navidrome concurrently
    async def _match(t: dict) -> YtTrackScan:
        from fix_artists import split_artist
        raw_artist = t.get("artist", "")
        found, nav_id = await _run_blocking(
            find_in_navidrome, t["title"], raw_artist
        )
        artists = split_artist(raw_artist) or ([raw_artist.strip()] if raw_artist.strip() else [])
        return YtTrackScan(
            video_id=t["video_id"],
            title=t["title"],
            artists=artists,
            duration=t.get("duration"),
            thumbnail=t.get("thumbnail"),
            in_navidrome=found,
            navidrome_id=nav_id,
        )

    tracks = await asyncio.gather(*[_match(t) for t in playlist["tracks"]])

    matched = sum(1 for t in tracks if t.in_navidrome)
    logger.info(
        "YT scan done: playlist=%r  total=%d  matched=%d",
        playlist["playlist_name"], len(tracks), matched,
    )

    return YtPlaylistScan(
        playlist_id=playlist["playlist_id"],
        playlist_name=playlist["playlist_name"],
        tracks=list(tracks),
    )


@router.post("/yt-import", response_model=JobStatus, status_code=202)
async def yt_import(req: YtImportRequest):
    """
    Enqueue a background job that downloads unmatched tracks from YouTube
    and uploads them to the music library via SFTP.
    """
    from api.jobs import get_redis

    to_download = [t for t in req.tracks if not t.in_navidrome and not t.skip]
    if not to_download:
        raise HTTPException(400, "No tracks to download (all matched or skipped)")

    redis = await get_redis()
    job = await redis.enqueue_job("yt_import_task", req.model_dump())
    logger.info(
        "Enqueued yt_import_task as job %s (%d tracks to download)",
        job.job_id, len(to_download),
    )
    return JobStatus(job_id=job.job_id, status="queued")
