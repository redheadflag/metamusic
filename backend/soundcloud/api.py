"""
SoundCloud API v2 client using httpx.
"""

import base64
import os
import re
import logging
import threading
import time
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

SC_API = "https://api-v2.soundcloud.com"
SC_CLIENT_ID = os.environ.get("SC_CLIENT_ID", "")  # optional override
SC_OAUTH_TOKEN = os.environ.get("SC_OAUTH_TOKEN", "")
HTTPS_PROXY = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or None

_SCRAPE_TTL = 3600  # seconds before re-scraping the client_id
_scraped_client_id: str = ""
_scraped_at: float = 0.0
_scrape_lock = threading.Lock()

_BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://soundcloud.com/",
    "Origin": "https://soundcloud.com",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
}


def _scrape_client_id() -> str:
    """Extract a fresh client_id from SoundCloud's bundled JS."""
    with httpx.Client(headers=_BROWSER_HEADERS, follow_redirects=True, timeout=20,
                      proxy=HTTPS_PROXY) as client:
        r = client.get("https://soundcloud.com")
        r.raise_for_status()
        script_urls = re.findall(
            r'<script[^>]+src="(https://a-v2\.sndcdn\.com/assets/[^"]+\.js)"',
            r.text,
        )
        for url in reversed(script_urls):
            try:
                sr = client.get(url, timeout=15)
                m = re.search(r'[,{]client_id:"([a-zA-Z0-9]+)"', sr.text)
                if m:
                    logger.info("Scraped fresh SC client_id from %s", url)
                    return m[1]
            except Exception:
                continue
    raise RuntimeError("Could not scrape a SoundCloud client_id from the web app")


def _get_client_id() -> str:
    global _scraped_client_id, _scraped_at

    if SC_CLIENT_ID:
        return SC_CLIENT_ID

    with _scrape_lock:
        if _scraped_client_id and (time.monotonic() - _scraped_at) < _SCRAPE_TTL:
            return _scraped_client_id
        _scraped_client_id = _scrape_client_id()
        _scraped_at = time.monotonic()
        return _scraped_client_id


def _invalidate_client_id() -> None:
    global _scraped_at
    with _scrape_lock:
        _scraped_at = 0.0


def _client() -> httpx.Client:
    headers = dict(_BROWSER_HEADERS)
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
    p["client_id"] = _get_client_id()

    url = f"{SC_API}{path}"
    logger.info("SC API: GET %s", url)

    with _client() as client:
        resp = client.get(url, params=p)
        if resp.status_code == 403 and not SC_CLIENT_ID:
            # client_id expired; scrape a fresh one and retry once
            logger.warning("SC client_id returned 403 — scraping a fresh one")
            _invalidate_client_id()
            p["client_id"] = _get_client_id()
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


_cover_cache: dict[str, Optional[bytes]] = {}


def _fetch_cover_cached(artwork_url: Optional[str]) -> Optional[bytes]:
    if not artwork_url:
        return None
    url = re.sub(r"-(large|t500x500|small|badge|tiny|crop)\b", "-t500x500", artwork_url)
    if url not in _cover_cache:
        _cover_cache[url] = _fetch_cover(artwork_url)
    return _cover_cache[url]


def _parse_track(raw: dict, index: int, total: int) -> dict:
    from fix_artists import split_artist

    pub_meta = raw.get("publisher_metadata") or {}

    title = pub_meta.get("release_title") or raw.get("title") or "Unknown Track"
    artist_raw = (
        pub_meta.get("artist")
        or raw.get("user", {}).get("username")
        or "Unknown Artist"
    )
    artists = split_artist(artist_raw) or [artist_raw.strip()]
    album = pub_meta.get("album_title") or ""

    # Prefer the explicit release date from publisher metadata;
    # fall back to the track's created_at only as a last resort.
    release_date = (
        pub_meta.get("release_date") or pub_meta.get("p_line_for_display") or ""
    )
    release_year = (
        release_date[:4] if release_date else (raw.get("created_at") or "")[:4]
    )

    artwork_url = raw.get("artwork_url") or raw.get("user", {}).get("avatar_url")
    cover_bytes = _fetch_cover_cached(artwork_url)
    cover_b64 = base64.b64encode(cover_bytes).decode() if cover_bytes else None

    sc_url = raw.get("permalink_url") or ""
    track_number = index if total > 1 else None

    return dict(
        title=title,
        artists=artists,
        album_artists=artists,
        album=album,
        release_year=release_year,
        track_number=track_number,
        cover_art_b64=cover_b64,
        sc_url=sc_url,
        file_name=f"{title}.mp3",
        temp_path="",
    )


def _parse_playlist(playlist: dict) -> dict:
    """Convert a SC API playlist object to an AlbumMeta-like dict."""
    tracks_raw = playlist.get("tracks") or []
    full_tracks = []
    for i, t in enumerate(tracks_raw, 1):
        if "title" not in t:
            try:
                t = _get(f"/tracks/{t['id']}")
            except Exception as e:
                logger.warning("Could not fetch track %s: %s", t.get("id"), e)
                continue
        full_tracks.append(_parse_track(t, i, len(tracks_raw)))

    if not full_tracks:
        return {}

    first = full_tracks[0]
    cover_url = playlist.get("artwork_url") or (
        tracks_raw[0].get("artwork_url") if tracks_raw else None
    )
    cover_bytes = _fetch_cover_cached(cover_url)
    cover_b64 = (
        base64.b64encode(cover_bytes).decode()
        if cover_bytes
        else first.get("cover_art_b64")
    )

    return dict(
        zip_name=playlist.get("permalink_url") or playlist.get("title") or "Unknown",
        tracks=full_tracks,
        artists=list(first["artists"]),
        album_artists=list(first["artists"]),
        album=playlist.get("title") or first["album"] or "Unknown Album",
        release_year=first["release_year"],
        cover_art_b64=cover_b64,
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
            full_tracks.append((t, i, len(tracks_raw)))
        return full_tracks

    raise ValueError(f"Unsupported SoundCloud resource kind: {kind!r}")


def _clean_artist_url(sc_url: str) -> str:
    """Strip UI-only path suffixes that the API resolve endpoint doesn't understand."""
    return re.sub(
        r"/(albums|tracks|sets|likes|following|followers|reposts|spotlight)\/?$",
        "",
        sc_url.rstrip("/"),
    )


def resolve_artist(sc_url: str) -> list[dict]:
    """
    Fetch all albums/playlists and loose tracks for a SoundCloud artist URL.
    Returns a list of AlbumMeta-like dicts (one per playlist + one for loose tracks).
    """
    sc_url = _clean_artist_url(sc_url)
    data = _get("/resolve", {"url": sc_url})
    kind = data.get("kind")
    if kind != "user":
        raise ValueError(f"Expected a user/artist URL, got kind={kind!r}")

    user_id = data["id"]
    username = data.get("username") or data.get("permalink") or str(user_id)
    logger.info("Fetching artist profile: %s (id=%s)", username, user_id)

    playlists_data = _get(
        f"/users/{user_id}/playlists", {"limit": 50, "representation": "full"}
    )
    playlists = (
        playlists_data
        if isinstance(playlists_data, list)
        else playlists_data.get("collection", [])
    )
    logger.info("Found %d playlists for %s", len(playlists), username)

    albums = []
    playlist_track_ids: set[int] = set()

    for pl in playlists:
        album = _parse_playlist(pl)
        if album:
            albums.append(album)
            for t in pl.get("tracks") or []:
                playlist_track_ids.add(t.get("id"))

    # loose = []
    # try:
    #     tracks_data = _get(f"/users/{user_id}/tracks", {"limit": 50})
    #     all_tracks = tracks_data if isinstance(tracks_data, list) else tracks_data.get("collection", [])
    #     loose = [t for t in all_tracks if t.get("id") not in playlist_track_ids]
    #     logger.info("Found %d loose tracks for %s", len(loose), username)
    # except Exception as e:
    #     logger.warning("Could not fetch loose tracks for %s (skipping): %s", username, e)

    # if loose:
    #     parsed = [_parse_track(t, i + 1, len(loose)) for i, t in enumerate(loose)]
    #     first = parsed[0]
    #     albums.append(dict(
    #         zip_name=f"{username} — loose tracks",
    #         tracks=parsed,
    #         artist=first["artist"],
    #         album_artist=first["artist"],
    #         album="",  # user will fill in
    #         release_year=first["release_year"],
    #         cover_art_b64=first.get("cover_art_b64"),
    #     ))

    return albums
