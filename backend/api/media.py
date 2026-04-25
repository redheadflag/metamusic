"""
Unified media import API (YouTube + SoundCloud).

POST /api/scan              — detect source, fetch metadata, run Navidrome matching
POST /api/import            — queue tracks + update Navidrome playlist
GET  /api/queue             — list queue
POST /api/queue/claim       — worker claims jobs
POST /api/queue/{id}/done   — worker reports success
POST /api/queue/{id}/failed — worker reports failure
POST /api/sc-fetch-artist   — fetch all albums for a SoundCloud artist URL

Claim/done/failed require X-Puller-Token header (env YT_PULLER_TOKEN).
"""

import asyncio
import logging
import os
import uuid
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Depends, Header, HTTPException

from models import JobStatus, MediaImportRequest, MediaScanResult, MediaTrackScan

logger = logging.getLogger(__name__)
router = APIRouter()

_executor = ThreadPoolExecutor(max_workers=4)
_PULLER_TOKEN = os.environ.get("YT_PULLER_TOKEN", "")


def _run_blocking(fn, *args):
    loop = asyncio.get_event_loop()
    return loop.run_in_executor(_executor, fn, *args)


async def _check_puller_token(x_puller_token: str = Header(default=None)):
    if not _PULLER_TOKEN or x_puller_token != _PULLER_TOKEN:
        raise HTTPException(403, "Invalid or missing X-Puller-Token")


def _detect_source(url: str) -> str:
    if "youtube.com" in url or "youtu.be" in url:
        return "youtube"
    if "soundcloud.com" in url:
        return "soundcloud"
    raise ValueError(f"Unrecognized URL — expected YouTube or SoundCloud: {url!r}")


def _is_yt_playlist(url: str) -> bool:
    return "/playlist?" in url or ("list=" in url and "watch?v=" not in url)


@router.post("/scan", response_model=MediaScanResult)
async def scan(body: dict):
    """Detect source from URL, fetch metadata, run Navidrome matching."""
    from youtube.matcher import find_in_navidrome
    from youtube.playlist import fetch_playlist, fetch_video
    from fix_artists import split_artist

    url = (body.get("url") or "").strip()
    if not url:
        raise HTTPException(400, "url is required")

    try:
        source = _detect_source(url)
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    logger.info("Scan requested: source=%s url=%s", source, url)

    raw_tracks: list[dict] = []
    scan_type = "single"
    playlist_name = ""

    if source == "youtube":
        if _is_yt_playlist(url):
            try:
                pl = await _run_blocking(fetch_playlist, url)
            except Exception as exc:
                logger.error("YT playlist fetch error: %s", exc)
                raise HTTPException(400, str(exc))
            scan_type = "playlist"
            playlist_name = pl["playlist_name"]
            for t in pl["tracks"]:
                artists = split_artist(t.get("artist", "")) or (
                    [t["artist"].strip()] if t.get("artist", "").strip() else []
                )
                raw_tracks.append({
                    "source_id": t["video_id"],
                    "source_url": f"https://www.youtube.com/watch?v={t['video_id']}",
                    "title": t["title"],
                    "artists": artists,
                    "duration": t.get("duration"),
                    "thumbnail": t.get("thumbnail"),
                })
        else:
            try:
                v = await _run_blocking(fetch_video, url)
            except Exception as exc:
                logger.error("YT video fetch error: %s", exc)
                raise HTTPException(400, str(exc))
            scan_type = "single"
            playlist_name = v["title"]
            artists = split_artist(v.get("artist", "")) or (
                [v["artist"].strip()] if v.get("artist", "").strip() else []
            )
            raw_tracks.append({
                "source_id": v["video_id"],
                "source_url": f"https://www.youtube.com/watch?v={v['video_id']}",
                "title": v["title"],
                "artists": artists,
                "duration": v.get("duration"),
                "thumbnail": v.get("thumbnail"),
            })

    else:  # soundcloud
        from soundcloud.api import resolve_for_scan
        try:
            sc_result = await _run_blocking(resolve_for_scan, url)
        except Exception as exc:
            logger.error("SC resolve error: %s", exc)
            raise HTTPException(400, str(exc))
        scan_type = sc_result["kind"]
        playlist_name = sc_result["playlist_name"]
        raw_tracks = sc_result["tracks"]

    # Run Navidrome matching for all tracks concurrently
    async def _match(t: dict) -> MediaTrackScan:
        artist = (t.get("artists") or [""])[0]
        found, nav_id = await _run_blocking(find_in_navidrome, t["title"], artist)
        return MediaTrackScan(
            source_id=t["source_id"],
            source_url=t["source_url"],
            title=t["title"],
            artists=t.get("artists") or [],
            album_artists=t.get("album_artists") or [],
            album=t.get("album") or "",
            release_year=t.get("release_year") or "",
            duration=t.get("duration"),
            thumbnail=t.get("thumbnail"),
            cover_art_b64=t.get("cover_art_b64"),
            in_navidrome=found,
            navidrome_id=nav_id,
        )

    tracks = list(await asyncio.gather(*[_match(t) for t in raw_tracks]))
    matched = sum(1 for t in tracks if t.in_navidrome)
    logger.info(
        "Scan done: source=%s type=%s playlist=%r total=%d matched=%d",
        source, scan_type, playlist_name, len(tracks), matched,
    )
    return MediaScanResult(
        source=source,
        type=scan_type,
        playlist_name=playlist_name,
        tracks=tracks,
    )


@router.post("/import", response_model=JobStatus, status_code=202)
async def media_import(req: MediaImportRequest):
    """Add matched tracks to Navidrome playlist; queue unmatched tracks for download."""
    from services import download_queue, navidrome_playlists

    to_download = [t for t in req.tracks if not t.in_navidrome and not t.skip]
    in_navidrome = [t for t in req.tracks if t.in_navidrome and t.navidrome_id and not t.skip]

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
                req.username,
            )
            logger.info("Navidrome playlist %r id=%s", req.playlist_name, playlist_id)
        except Exception as exc:
            logger.warning("Playlist create/update failed (non-fatal): %s", exc)

    # Enqueue unmatched tracks in SQLite
    for i, track in enumerate(to_download, 1):
        if req.download_mode == "album":
            album = req.album_title or track.album
            album_artist = req.album_artist or (
                track.album_artists[0] if track.album_artists else ""
            )
            release_year = req.release_year or track.release_year
            album_artists = [album_artist] if album_artist else list(track.album_artists)
        else:
            album = track.album
            album_artists = list(track.album_artists)
            release_year = track.release_year

        await _run_blocking(
            download_queue.enqueue,
            track.source_id,
            track.title,
            list(track.artists),
            album_artists,
            album,
            release_year,
            track.thumbnail,
            track.cover_art_b64,
            track.duration,
            playlist_id,
            req.playlist_name,
            req.source,
            track.source_url,
            req.download_mode,
            req.album_cover_b64 if req.download_mode == "album" else None,
            i,
        )

    logger.info(
        "Import: source=%s mode=%s playlist=%r queued=%d in_navidrome=%d",
        req.source, req.download_mode, req.playlist_name,
        len(to_download), len(in_navidrome),
    )
    return JobStatus(job_id=str(uuid.uuid4()), status="queued")


@router.get("/queue")
async def queue_list(status: str | None = None):
    """List all queue entries. Filter with ?status=pending|claimed|done|failed."""
    from services import download_queue
    return await _run_blocking(download_queue.list_all, status)


@router.post("/queue/claim")
async def queue_claim(
    body: dict,
    _: None = Depends(_check_puller_token),
):
    """Worker claims pending jobs."""
    from services import download_queue

    worker_id = str(body.get("worker_id", "unknown"))
    limit = int(body.get("limit", 5))
    return await _run_blocking(download_queue.claim, limit, worker_id)


@router.post("/queue/{job_id}/done")
async def queue_done(
    job_id: int,
    body: dict,
    _: None = Depends(_check_puller_token),
):
    """Worker reports successful upload. Triggers Navidrome scan + playlist append."""
    from services import download_queue, navidrome_playlists
    from services.navidrome import trigger_scan

    job = await _run_blocking(download_queue.get_by_id, job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    remote_path = str(body.get("remote_path", ""))

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


@router.post("/queue/{job_id}/failed")
async def queue_failed(
    job_id: int,
    body: dict,
    _: None = Depends(_check_puller_token),
):
    """Worker reports failure."""
    from services import download_queue

    job = await _run_blocking(download_queue.get_by_id, job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    error = str(body.get("error", "unknown error"))
    await _run_blocking(download_queue.mark_failed, job_id, error)
    return {"status": "failed"}


@router.post("/sc-fetch-artist")
async def sc_fetch_artist(body: dict):
    """Fetch all albums for a SoundCloud artist profile URL."""
    from soundcloud.api import resolve_artist

    url = (body.get("url") or "").strip()
    if not url:
        raise HTTPException(400, "url is required")

    logger.info("SC artist fetch: %s", url)
    try:
        albums = await _run_blocking(resolve_artist, url)
    except Exception as exc:
        logger.error("SC artist API error: %s", exc)
        raise HTTPException(400, str(exc))

    logger.info("SC artist: %d album(s) found", len(albums))
    return albums
