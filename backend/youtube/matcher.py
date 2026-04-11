"""
Fuzzy-match a YouTube track title/artist against the Navidrome/Subsonic library.
Uses the same admin credentials as services/navidrome.py.
"""

import hashlib
import logging
import os
import re
import secrets
import unicodedata

import httpx

logger = logging.getLogger(__name__)

NAVIDROME_URL = os.environ.get("NAVIDROME_URL", "").rstrip("/")
NAVIDROME_ADMIN_USER = os.environ.get("NAVIDROME_ADMIN_USER", "")
NAVIDROME_ADMIN_PASSWORD = os.environ.get("NAVIDROME_ADMIN_PASSWORD", "")

_SUBSONIC_API_VERSION = "1.16.1"
_CLIENT = "metamusic-yt"

# A track is considered matched when the weighted title+artist score meets this.
# 0.55 is intentionally lenient to catch minor spelling differences.
MATCH_THRESHOLD = 0.55


def _auth_params() -> dict:
    salt = secrets.token_hex(8)
    token = hashlib.md5((NAVIDROME_ADMIN_PASSWORD + salt).encode()).hexdigest()
    return {
        "u": NAVIDROME_ADMIN_USER,
        "t": token,
        "s": salt,
        "v": _SUBSONIC_API_VERSION,
        "c": _CLIENT,
        "f": "json",
    }


def _normalize(s: str) -> str:
    """Lowercase, strip accents, replace non-word chars with spaces."""
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _word_sim(a: str, b: str) -> float:
    """Jaccard similarity on word sets."""
    na, nb = _normalize(a), _normalize(b)
    if na == nb:
        return 1.0
    wa, wb = set(na.split()), set(nb.split())
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def find_in_navidrome(title: str, artist: str = "") -> tuple[bool, str | None]:
    """
    Search Navidrome for a track by title (+ optional artist).
    Returns (found: bool, navidrome_song_id: str | None).
    """
    if not NAVIDROME_URL or not NAVIDROME_ADMIN_USER:
        logger.debug("Navidrome URL/credentials not configured — skipping match")
        return False, None

    try:
        params = _auth_params()
        params.update({
            "query": title,
            "songCount": 15,
            "albumCount": 0,
            "artistCount": 0,
        })
        resp = httpx.get(
            f"{NAVIDROME_URL}/rest/search3",
            params=params,
            timeout=10,
        )
        resp.raise_for_status()
        songs = (
            resp.json()
            .get("subsonic-response", {})
            .get("searchResult3", {})
            .get("song", [])
        )
    except Exception as exc:
        logger.warning("Navidrome search failed for %r: %s", title, exc)
        return False, None

    best_score, best_id = 0.0, None
    for song in songs:
        title_score = _word_sim(title, song.get("title", ""))
        # When no artist provided, assign a neutral weight so title alone decides
        artist_score = _word_sim(artist, song.get("artist", "")) if artist else 0.5
        score = title_score * 0.7 + artist_score * 0.3
        if score > best_score:
            best_score = score
            best_id = song.get("id")

    if best_score >= MATCH_THRESHOLD and best_id:
        logger.debug(
            "Matched %r (artist=%r) → id=%s score=%.2f",
            title, artist, best_id, best_score,
        )
        return True, best_id

    logger.debug("No match for %r (artist=%r) best=%.2f", title, artist, best_score)
    return False, None
