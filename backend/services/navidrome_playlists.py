"""
Navidrome playlist management via the Subsonic API.

Uses the same env-vars as backend/services/navidrome.py:
  NAVIDROME_URL, NAVIDROME_ADMIN_USER, NAVIDROME_ADMIN_PASSWORD
"""

import hashlib
import logging
import os
import secrets
import time

import httpx

logger = logging.getLogger(__name__)

NAVIDROME_URL = os.environ["NAVIDROME_URL"].rstrip("/")
NAVIDROME_ADMIN_USER = os.environ["NAVIDROME_ADMIN_USER"]
NAVIDROME_ADMIN_PASSWORD = os.environ["NAVIDROME_ADMIN_PASSWORD"]

_API_VERSION = "1.16.1"
_CLIENT_NAME = "metamusic-backend"


def _auth() -> dict:
    salt = secrets.token_hex(8)
    token = hashlib.md5((NAVIDROME_ADMIN_PASSWORD + salt).encode()).hexdigest()
    return {
        "u": NAVIDROME_ADMIN_USER,
        "t": token,
        "s": salt,
        "v": _API_VERSION,
        "c": _CLIENT_NAME,
        "f": "json",
    }


def _get(endpoint: str, extra: dict | None = None) -> dict:
    params = {**_auth(), **(extra or {})}
    r = httpx.get(f"{NAVIDROME_URL}/rest/{endpoint}", params=params, timeout=15)
    r.raise_for_status()
    body = r.json().get("subsonic-response", {})
    if body.get("status") != "ok":
        raise RuntimeError(f"Subsonic {endpoint} error: {body.get('error', body)}")
    return body


def _jwt_token() -> str:
    """Authenticate as admin and return a JWT for native /api/* endpoints."""
    r = httpx.post(
        f"{NAVIDROME_URL}/auth/login",
        json={"username": NAVIDROME_ADMIN_USER, "password": NAVIDROME_ADMIN_PASSWORD},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()["token"]


def _find_user_id(username: str) -> str | None:
    """Return the Navidrome user ID for *username*, or None if not found."""
    token = _jwt_token()
    r = httpx.get(
        f"{NAVIDROME_URL}/api/user",
        headers={"X-ND-Authorization": f"Bearer {token}"},
        timeout=10,
    )
    r.raise_for_status()
    for user in r.json():
        if user.get("userName", "").lower() == username.lower():
            return str(user["id"])
    return None


def _set_playlist_owner(pl_id: str, owner_id: str) -> None:
    """Transfer playlist ownership to *owner_id* via the native API."""
    token = _jwt_token()
    r = httpx.put(
        f"{NAVIDROME_URL}/api/playlist/{pl_id}",
        json={"ownerId": owner_id},
        headers={"X-ND-Authorization": f"Bearer {token}"},
        timeout=10,
    )
    r.raise_for_status()


def _find_playlist_id(name: str) -> str | None:
    body = _get("getPlaylists")
    for pl in body.get("playlists", {}).get("playlist", []):
        if pl.get("name") == name:
            return pl["id"]
    return None


def create_or_update_playlist(name: str, song_ids: list, username: str = "") -> str:
    """
    Create (or look up existing) playlist by name.
    *song_ids* are appended via updatePlaylist if the playlist already exists,
    or used as the initial song list on creation.
    If *username* is given, ownership is transferred to that user (falls back to
    admin if the username is not found in Navidrome).
    Returns the Navidrome playlist id.
    """
    existing_id = _find_playlist_id(name)

    if existing_id:
        # Append new songs without replacing existing ones
        for sid in song_ids:
            try:
                _get("updatePlaylist", {"playlistId": existing_id, "songIdToAdd": sid})
            except Exception as exc:
                logger.warning("updatePlaylist append failed for song %s: %s", sid, exc)
        return existing_id

    # Create new playlist with the given songs
    # Subsonic accepts repeated songId params via a list of tuples
    auth_items = list(_auth().items())
    query: list[tuple] = auth_items + [("name", name)]
    for sid in song_ids:
        query.append(("songId", sid))

    r = httpx.get(f"{NAVIDROME_URL}/rest/createPlaylist", params=query, timeout=15)
    r.raise_for_status()
    body = r.json().get("subsonic-response", {})
    if body.get("status") != "ok":
        raise RuntimeError(f"createPlaylist error: {body.get('error', body)}")
    pl_id = str(body.get("playlist", {}).get("id", ""))
    if not pl_id:
        # Some Navidrome versions don't return the playlist in createPlaylist;
        # look it up by name as a fallback.
        pl_id = _find_playlist_id(name) or ""
    if pl_id:
        try:
            _get("updatePlaylist", {"playlistId": pl_id, "public": "true"})
        except Exception as exc:
            logger.warning("Could not set playlist %s to public: %s", pl_id, exc)
        if username:
            try:
                uid = _find_user_id(username)
                if uid is None:
                    logger.warning(
                        "User %r not found in Navidrome — playlist owned by admin", username
                    )
                    uid = _find_user_id(NAVIDROME_ADMIN_USER)
                if uid:
                    _set_playlist_owner(pl_id, uid)
                    logger.info("Playlist %s owner set to %s (%s)", pl_id, username, uid)
            except Exception as exc:
                logger.warning("Could not set playlist owner to %r: %s", username, exc)
    return pl_id


def append_to_playlist(playlist_id: str, song_id: str) -> None:
    """Add a single song to an existing playlist."""
    _get("updatePlaylist", {"playlistId": playlist_id, "songIdToAdd": song_id})


def find_song_by_title_artist(
    title: str,
    artist: str,
    retries: int = 3,
    delay: float = 5.0,
) -> str | None:
    """
    Search Navidrome for a song by title + artist with retries to allow scan lag.
    Returns the Subsonic song id or None.
    """
    for attempt in range(retries):
        try:
            body = _get(
                "search3",
                {"query": title, "songCount": 20, "artistCount": 0, "albumCount": 0},
            )
            songs = body.get("searchResult3", {}).get("song", [])
            for s in songs:
                if s.get("title", "").lower() == title.lower():
                    s_artist = s.get("artist", "").lower()
                    a_lower = artist.lower()
                    if not artist or a_lower in s_artist or s_artist in a_lower:
                        return str(s["id"])
        except Exception as exc:
            logger.warning("find_song attempt %d/%d failed: %s", attempt + 1, retries, exc)
        if attempt < retries - 1:
            time.sleep(delay)
    return None
