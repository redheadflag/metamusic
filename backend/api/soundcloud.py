import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, HTTPException

from models import TrackMeta

logger = logging.getLogger(__name__)
router = APIRouter()

_executor = ThreadPoolExecutor(max_workers=4)


def _run_blocking(fn, *args):
    loop = asyncio.get_event_loop()
    return loop.run_in_executor(_executor, fn, *args)


@router.post("/sc-fetch")
async def sc_fetch(body: dict):
    """Fetch metadata from a SoundCloud URL via SC API v2."""
    from soundcloud.api import resolve_url

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
            "SC entry %d: title=%r artists=%r album=%r url=%s",
            i,
            t.title,
            t.artists,
            t.album,
            t.sc_url,
        )
    return results


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
    except Exception as e:
        logger.error("SC artist API error: %s", e)
        raise HTTPException(400, str(e))

    logger.info("SC artist: %d album(s) found", len(albums))
    return albums
