import logging
import os

import httpx

logger = logging.getLogger(__name__)

NAVIDROME_URL           = os.environ["NAVIDROME_URL"].rstrip("/")
NAVIDROME_ADMIN_USER    = os.environ["NAVIDROME_ADMIN_USER"]
NAVIDROME_ADMIN_PASSWORD = os.environ["NAVIDROME_ADMIN_PASSWORD"]


async def _get_token(client: httpx.AsyncClient) -> str:
    """Authenticate as admin and return a JWT token."""
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
    Trigger a Navidrome library scan via the REST API.
    Non-fatal: logs a warning on failure and continues.
    """
    try:
        async with httpx.AsyncClient() as client:
            token = await _get_token(client)
            response = await client.post(
                f"{NAVIDROME_URL}/api/scanner/trigger",
                headers={"X-ND-Authorization": f"Bearer {token}"},
                timeout=10,
            )
            response.raise_for_status()
            logger.info("Navidrome scan triggered: %s", response.json())
    except Exception as exc:
        logger.warning("Navidrome scan trigger failed (non-fatal): %s", exc)
