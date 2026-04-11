"""
ARQ task functions.

After each task completes:
  1. Navidrome library scan is triggered so tracks appear immediately.
"""

import logging

logger = logging.getLogger(__name__)


async def _post_process() -> None:
    """Trigger a Navidrome scan."""
    from services.navidrome import trigger_scan

    await trigger_scan()


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
        ctx["job_id"],
        req.artist,
        req.album,
        len(req.tracks),
    )

    saved = process_album(req)
    logger.info("[job %s] stored (raw): %s", ctx["job_id"], saved)

    await _post_process()
    return {"saved": saved}


# ---------------------------------------------------------------------------
# task: sc_process_task  (POST /api/sc-process)
# ---------------------------------------------------------------------------


async def sc_process_task(ctx, req_dict: dict) -> dict:
    """Download SoundCloud tracks in native format and store."""
    from models import ScProcessRequest
    from processing import process_sc_album

    req = ScProcessRequest(**req_dict)

    logger.info(
        "[job %s] sc_process_task: artist=%r album=%r tracks=%d",
        ctx["job_id"],
        req.artist,
        req.album,
        len(req.tracks),
    )

    saved = await process_sc_album(req)
    logger.info("[job %s] SC stored (raw): %s", ctx["job_id"], saved)

    await _post_process()
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
        ctx["job_id"],
        len(req.albums),
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

    await _post_process()
    return {"saved": all_saved}


# ---------------------------------------------------------------------------
# task: yt_import_task  (POST /api/yt-import)
# ---------------------------------------------------------------------------


async def yt_import_task(ctx, req_dict: dict) -> dict:
    """Download YouTube tracks and upload to the music library via SFTP."""
    import asyncio
    import os
    import re
    import shutil
    import tempfile
    from concurrent.futures import ThreadPoolExecutor

    from models import YtImportRequest
    from services.sftp import album_path, upload_file, write_album_file
    from youtube.downloader import download_youtube_track, retag_mp3, run_fix_artists

    req = YtImportRequest(**req_dict)

    _executor = ThreadPoolExecutor(max_workers=2)

    def _safe(s: str) -> str:
        return re.sub(r'[\\/*?:"<>|]', "_", s).strip()

    def _download_and_upload(track) -> str:
        tmp_dir = tempfile.mkdtemp(prefix="yt_dl_")
        try:
            # 1. Download as MP3 (yt-dlp embeds YouTube metadata)
            mp3_path = download_youtube_track(
                video_id=track.video_id,
                dest_dir=tmp_dir,
            )

            # 2. Override text tags with user-edited title / artist,
            #    preserving the embedded thumbnail added by yt-dlp.
            retag_mp3(
                mp3_path,
                title=track.title,
                artist=track.artist,
                album=f"{track.title} (Single)",
            )

            # 3. Run fix-artists.sh to split multi-value artist tags
            #    (non-fatal; logged as warning on failure)
            run_fix_artists(tmp_dir)

            # 4. Upload to SFTP  →  <artist>/<title> (Single)/<title>.mp3
            ext = os.path.splitext(mp3_path)[1].lower() or ".mp3"
            album_name = f"{_safe(track.title)} (Single)"
            fname = _safe(track.title) + ext
            remote = album_path(_safe(track.artist), album_name, fname)
            upload_file(mp3_path, remote)

            # 5. Write .album control file (no format conversion needed for MP3)
            write_album_file(_safe(track.artist), album_name, needs_processing=False)

            return remote
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    loop = asyncio.get_running_loop()
    results: list[dict] = []

    for track in req.tracks:
        if track.in_navidrome or track.skip:
            continue
        try:
            path = await loop.run_in_executor(
                _executor, _download_and_upload, track
            )
            results.append({"video_id": track.video_id, "status": "ok", "path": path})
            logger.info(
                "[job %s] YT downloaded: %s → %s",
                ctx["job_id"], track.video_id, path,
            )
        except Exception as exc:
            logger.error(
                "[job %s] YT download failed for %s: %s",
                ctx["job_id"], track.video_id, exc,
            )
            results.append({
                "video_id": track.video_id,
                "status": "error",
                "error": str(exc),
            })

    await _post_process()
    return {"results": results}


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
        yt_import_task,
    ]

    redis_settings = get_redis_settings()

    # A SoundCloud artist import can easily take many minutes:
    # ~30 s/track x 50 tracks + SFTP uploads = well over an hour.
    # 24 h is a safe upper bound for any realistic personal-library job;
    # if something is still running after that it has genuinely hung.
    job_timeout = 14400  # 4 hours

    # No automatic retries. SC download failures are almost always auth/
    # network issues that won't self-heal in milliseconds, and retrying a
    # timed-out bulk import just doubles wasted time and API quota.
    max_tries = 2

    # Keep result in Redis for 1 h after completion so the job status
    # endpoint can still return "complete" if polled shortly after.
    keep_result = 3600

    max_jobs = 4
