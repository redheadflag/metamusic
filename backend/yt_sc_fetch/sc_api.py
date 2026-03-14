"""
SoundCloud API v2 client.
Uses api-v2.soundcloud.com with OAuth token + auto-fetched client_id.

client_id is scraped from SoundCloud's own JS bundle on first use and cached.
oauth_token comes from SC_OAUTH_TOKEN env var.
"""

import base64
import os
import urllib.request
import urllib.parse
import json
import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

SC_API        = "https://api-v2.soundcloud.com"
SC_OAUTH_TOKEN = os.environ.get("SC_OAUTH_TOKEN", "")

_client_id_cache: str = ""


def _fetch_client_id() -> str:
    """
    Scrape a fresh client_id from SoundCloud's homepage JS bundle.
    SC embeds it in their app scripts as client_id:"<value>".
    """
    logger.info("Fetching fresh SoundCloud client_id from JS bundle...")
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    req = urllib.request.Request("https://soundcloud.com", headers={"User-Agent": ua})
    with urllib.request.urlopen(req, timeout=20) as resp:
        html = resp.read().decode("utf-8", errors="ignore")

    script_urls = re.findall(r'<script[^>]+src="(https://[^"]+\.js)"', html)
    for script_url in reversed(script_urls):
        try:
            req = urllib.request.Request(script_url, headers={"User-Agent": ua})
            with urllib.request.urlopen(req, timeout=20) as resp:
                js = resp.read().decode("utf-8", errors="ignore")
            match = re.search(r'client_id\s*[=:]\s*["\']([a-zA-Z0-9_-]{20,})["\']', js)
            if match:
                cid = match.group(1)
                logger.info("Found client_id: %s…", cid[:8])
                return cid
        except Exception as e:
            logger.debug("Script %s failed: %s", script_url, e)

    raise RuntimeError("Could not extract client_id from SoundCloud JS bundle")


def _get_client_id() -> str:
    global _client_id_cache
    if not _client_id_cache:
        _client_id_cache = _fetch_client_id()
    return _client_id_cache


def _headers() -> dict:
    h = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Referer": "https://soundcloud.com/",
        "Origin": "https://soundcloud.com",
    }
    if SC_OAUTH_TOKEN:
        h["Authorization"] = f"OAuth {SC_OAUTH_TOKEN}"
    return h


def _get(path: str, params: dict | None = None) -> dict | list:
    global _client_id_cache
    p = dict(params or {})
    p["client_id"] = _get_client_id()
    query = urllib.parse.urlencode(p)
    url   = f"{SC_API}{path}?{query}"
    logger.info("SC API: GET %s", url)
    req = urllib.request.Request(url, headers=_headers())
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            # client_id stale — scrape a fresh one and retry once
            logger.warning("client_id rejected (%s), refreshing...", e.code)
            _client_id_cache = ""
            p["client_id"] = _get_client_id()
            query = urllib.parse.urlencode(p)
            url   = f"{SC_API}{path}?{query}"
            req   = urllib.request.Request(url, headers=_headers())
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read())
        raise


def _fetch_cover(artwork_url: Optional[str]) -> Optional[bytes]:
    if not artwork_url:
        return None
    url = re.sub(r"-(large|t500x500|small|badge|tiny|crop)\b", "-t500x500", artwork_url)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.read()
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
    year         = (raw.get("created_at") or "")[:4]
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
        release_year=year,
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
    logger.info("Resolved %s → kind=%s", sc_url, kind)

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