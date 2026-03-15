import hashlib
import logging
import os
import secrets

import httpx

logger = logging.getLogger(__name__)

NAVIDROME_URL            = os.environ["NAVIDROME_URL"].rstrip("/")
NAVIDROME_ADMIN_USER     = os.environ["NAVIDROME_ADMIN_USER"]
NAVIDROME_ADMIN_PASSWORD = os.environ["NAVIDROME_ADMIN_PASSWORD"]

# Subsonic API version string sent with every request
_SUBSONIC_API_VERSION = "1.16.1"
_SUBSONIC_CLIENT_NAME = "metamusic-backend"


def _subsonic_auth_params() -> dict:
    """
    Build Subsonic token-based auth params (no plaintext password on the wire).
    salt  – random hex string generated fresh for each call
    token – md5(password + salt)
    """
    salt  = secrets.token_hex(8)
    token = hashlib.md5((NAVIDROME_ADMIN_PASSWORD + salt).encode()).hexdigest()
    return {
        "u": NAVIDROME_ADMIN_USER,
        "t": token,
        "s": salt,
        "v": _SUBSONIC_API_VERSION,
        "c": _SUBSONIC_CLIENT_NAME,
        "f": "json",
    }


async def _get_token(client: httpx.AsyncClient) -> str:
    """Authenticate as admin and return a JWT token (used by the native /api/* endpoints)."""
    response = await client.post(
        f"{NAVIDROME_URL}/auth/login",
        json={"username": NAVIDROME_ADMIN_USER, "password": NAVIDROME_ADMIN_PASSWORD},
        timeout=10,
    )
    response.raise_for_status()
    return response.json()["token"]


async def create_navidrome_user(username: str, password: str) -> None:
    """
    Create a regular (non-admin) Navidrome user via the native REST API.
    Raises httpx.HTTPStatusError on a non-2xx response.
    """
    async with httpx.AsyncClient() as client:
        token = await _get_token(client)
        response = await client.post(
            f"{NAVIDROME_URL}/api/user",
            json={
                "userName": username,
                "password": password,
                "name": username,
                "isAdmin": False,
            },
            headers={"X-ND-Authorization": f"Bearer {token}"},
            timeout=10,
        )
        response.raise_for_status()


async def trigger_scan() -> None:
    """
    Trigger a full Navidrome library scan via the Subsonic API (startScan).

    Uses GET /rest/startScan with fullScan=true so every file is re-indexed,
    not just files whose timestamps changed since the last scan.

    Non-fatal: logs a warning on failure so the upload job still succeeds.
    """
    try:
        params = _subsonic_auth_params()
        params["fullScan"] = "true"

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{NAVIDROME_URL}/rest/startScan",
                params=params,
                timeout=10,
            )
            response.raise_for_status()

        body = response.json()
        status = (
            body.get("subsonic-response", {})
                .get("scanStatus", {})
        )
        logger.info("Navidrome full scan triggered: scanning=%s count=%s",
                    status.get("scanning"), status.get("count"))
    except Exception as exc:
        logger.warning("Navidrome scan trigger failed (non-fatal): %s", exc)
