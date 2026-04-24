"""
API endpoints for YouTube playlist import.

POST /api/yt-scan              — fetch playlist + check Navidrome
POST /api/yt-import            — add matched tracks to playlist; queue the rest
GET  /api/yt-queue             — list queue (optional ?status= filter)
POST /api/yt-queue/claim       — local worker claims pending jobs
POST /api/yt-queue/{id}/done   — local worker reports success
POST /api/yt-queue/{id}/failed — local worker reports failure

Claim/done/failed require X-Puller-Token header (env YT_PULLER_TOKEN).
"""

import asyncio
import logging
import os
import uuid
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Depends, Header, HTTPException

from models import JobStatus, YtImportRequest, YtPlaylistScan, YtTrackScan

logger = logging.getLogger(__name__)
router = APIRouter()

_executor = ThreadPoolExecutor(max_workers=4)
_YT_PULLER_TOKEN = os.environ.get("YT_PULLER_TOKEN", "")


def _run_blocking(fn, *args):
    loop = asyncio.get_event_loop()
    return loop.run_in_executor(_executor, fn, *args)


async def _check_puller_token(x_puller_token: str = Header(default=None)):
    if not _YT_PULLER_TOKEN or x_puller_token != _YT_PULLER_TOKEN:
        raise HTTPException(403, "Invalid or missing X-Puller-Token")


@router.post("/yt-fetch-video")
async def yt_fetch_video(body: dict):
    """Fetch metadata for a single YouTube video (no download)."""
    from youtube.playlist import fetch_video
    from fix_artists import split_artist

    url = (body.get("url") or "").strip()
    if not url:
        raise HTTPException(400, "url is required")

    logger.info("YT single video fetch: %s", url)
    try:
        data = await _run_blocking(fetch_video, url)
    except Exception as exc:
        logger.error("YT video fetch error: %s", exc)
        raise HTTPException(400, str(exc))

    raw_artist = data.get("artist", "")
    artists = split_artist(raw_artist) or ([raw_artist.strip()] if raw_artist.strip() else [])

    return {
        "video_id": data["video_id"],
        "title": data["title"],
        "artists": artists,
        "duration": data.get("duration"),
        "thumbnail": data.get("thumbnail"),
    }


@router.post("/yt-scan", response_model=YtPlaylistScan)
async def yt_scan(body: dict):
    """Fetch a YouTube playlist and check each track against the Navidrome library."""
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

    async def _match(t: dict) -> YtTrackScan:
        from fix_artists import split_artist
        raw_artist = t.get("artist", "")
        found, nav_id = await _run_blocking(find_in_navidrome, t["title"], raw_artist)
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
    Add already-matched tracks to a Navidrome playlist immediately.
    Enqueue unmatched tracks in the SQLite download queue for the local worker.
    """
    from services import download_queue, navidrome_playlists

    to_download = [t for t in req.tracks if not t.in_navidrome and not t.skip]
    in_navidrome = [t for t in req.tracks if t.in_navidrome and t.navidrome_id]

    if not to_download and not in_navidrome:
        raise HTTPException(400, "No tracks to import (all skipped)")

    # Create / update Navidrome playlist with already-matched tracks
    playlist_id: str | None = None
    if req.playlist_name:
        try:
            nav_ids = [t.navidrome_id for t in in_navidrome]
            playlist_id = await _run_blocking(
                navidrome_playlists.create_or_update_playlist,
                req.playlist_name,
                nav_ids,
            )
            logger.info("Navidrome playlist %r id=%s", req.playlist_name, playlist_id)
        except Exception as exc:
            logger.warning("Playlist create/update failed (non-fatal): %s", exc)

    # Enqueue pending tracks in SQLite
    for track in to_download:
        await _run_blocking(
            download_queue.enqueue,
            track.video_id,
            track.title,
            list(track.artists),
            list(track.album_artists),
            track.album,
            track.release_year,
            track.thumbnail,
            track.duration,
            playlist_id,
            req.playlist_name,
        )

    logger.info(
        "YT import: playlist=%r  queued=%d  in_navidrome=%d",
        req.playlist_name, len(to_download), len(in_navidrome),
    )
    return JobStatus(job_id=str(uuid.uuid4()), status="queued")


@router.get("/yt-queue")
async def yt_queue_list(status: str | None = None):
    """List all queue entries. Filter with ?status=pending|claimed|done|failed."""
    from services import download_queue
    return await _run_blocking(download_queue.list_all, status)


@router.post("/yt-queue/claim")
async def yt_queue_claim(
    body: dict,
    _: None = Depends(_check_puller_token),
):
    """Local worker claims pending jobs."""
    from services import download_queue

    worker_id = str(body.get("worker_id", "unknown"))
    limit = int(body.get("limit", 5))
    return await _run_blocking(download_queue.claim, limit, worker_id)


@router.post("/yt-queue/{job_id}/done")
async def yt_queue_done(
    job_id: int,
    body: dict,
    _: None = Depends(_check_puller_token),
):
    """Local worker reports successful upload. Triggers Navidrome playlist append."""
    from services import download_queue, navidrome_playlists
    from services.navidrome import trigger_scan

    job = await _run_blocking(download_queue.get_by_id, job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    remote_path = str(body.get("remote_path", ""))

    # Trigger scan so the new file is indexed
    await trigger_scan()

    navidrome_id: str | None = None
    if job.get("playlist_id"):
        try:
            artist = (job["artists"] or [""])[0]
            navidrome_id = await _run_blocking(
                navidrome_playlists.find_song_by_title_artist,
                job["title"],
                artist,
                3,
                5.0,
            )
            if navidrome_id:
                await _run_blocking(
                    navidrome_playlists.append_to_playlist,
                    job["playlist_id"],
                    navidrome_id,
                )
                logger.info(
                    "Appended song %s to playlist %s", navidrome_id, job["playlist_id"]
                )
        except Exception as exc:
            logger.warning("Playlist append failed (non-fatal): %s", exc)

    await _run_blocking(download_queue.mark_done, job_id, remote_path, navidrome_id)
    return {"status": "done"}


@router.post("/yt-queue/{job_id}/failed")
async def yt_queue_failed(
    job_id: int,
    body: dict,
    _: None = Depends(_check_puller_token),
):
    """Local worker reports failure."""
    from services import download_queue

    job = await _run_blocking(download_queue.get_by_id, job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    error = str(body.get("error", "unknown error"))
    await _run_blocking(download_queue.mark_failed, job_id, error)
    return {"status": "failed"}
