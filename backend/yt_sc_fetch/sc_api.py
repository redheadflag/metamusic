"""
SoundCloud API v2 client using httpx for better TLS fingerprinting.
"""

import base64
import os
import re
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

SC_API        = "https://api-v2.soundcloud.com"
SC_CLIENT_ID  = os.environ.get("SC_CLIENT_ID", "")
SC_OAUTH_TOKEN = os.environ.get("SC_OAUTH_TOKEN", "")
HTTPS_PROXY   = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or None


def _client() -> httpx.Client:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://soundcloud.com/",
        "Origin": "https://soundcloud.com",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-site",
    }
    if SC_OAUTH_TOKEN:
        headers["Authorization"] = f"OAuth {SC_OAUTH_TOKEN}"

    return httpx.Client(
        headers=headers,
        proxy=HTTPS_PROXY,
        timeout=30,
        follow_redirects=True,
    )


def _get(path: str, params: dict | None = None) -> dict | list:
    p = dict(params or {})
    if SC_CLIENT_ID:
        p["client_id"] = SC_CLIENT_ID

    url = f"{SC_API}{path}"
    logger.info("SC API: GET %s params=%s", url, p)

    with _client() as client:
        resp = client.get(url, params=p)
        resp.raise_for_status()
        return resp.json()


def _fetch_cover(artwork_url: Optional[str]) -> Optional[bytes]:
    if not artwork_url:
        return None
    url = re.sub(r"-(large|t500x500|small|badge|tiny|crop)\b", "-t500x500", artwork_url)
    try:
        with _client() as client:
            resp = client.get(url, timeout=20)
            resp.raise_for_status()
            return resp.content
    except Exception as e:
        logger.warning("Could not fetch cover art: %s", e)
        return None


def _parse_track(raw: dict, index: int, total: int) -> dict:
    pub_meta = raw.get("publisher_metadata") or {}

    title  = pub_meta.get("release_title") or raw.get("title") or "Unknown Track"
    artist = (
        pub_meta.get("artist")
        or raw.get("user", {}).get("username")
        or "Unknown Artist"
    )
    album        = pub_meta.get("album_title") or ""
    release_year = (raw.get("created_at") or "")[:4]

    artwork_url  = raw.get("artwork_url") or raw.get("user", {}).get("avatar_url")
    cover_bytes  = _fetch_cover(artwork_url)
    cover_b64    = base64.b64encode(cover_bytes).decode() if cover_bytes else None

    sc_url       = raw.get("permalink_url") or ""
    track_number = index if total > 1 else None

    return dict(
        title=title,
        artist=artist,
        album_artist=artist,
        album=album,
        release_year=release_year,
        track_number=track_number,
        cover_art_b64=cover_b64,
        sc_url=sc_url,
        file_name=f"{title}.mp3",
        temp_path="",
    )


def resolve_url(sc_url: str) -> list[dict]:
    """
    Resolve any SoundCloud URL and return a list of track dicts.
    Works for single tracks and playlists/sets/albums.
    """
    data = _get("/resolve", {"url": sc_url})
    kind = data.get("kind")
    logger.info("Resolved %s → kind=%s id=%s", sc_url, kind, data.get("id"))

    if kind == "track":
        return [_parse_track(data, 1, 1)]

    if kind == "playlist":
        tracks_raw = data.get("tracks") or []
        full_tracks = []
        for i, t in enumerate(tracks_raw, 1):
            if "title" not in t:
                try:
                    t = _get(f"/tracks/{t['id']}")
                except Exception as e:
                    logger.warning("Could not fetch track %s: %s", t.get("id"), e)
                    continue
            full_tracks.append(_parse_track(t, i, len(tracks_raw)))
        return full_tracks

    raise ValueError(f"Unsupported SoundCloud resource kind: {kind!r}")