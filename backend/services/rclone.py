"""
Trigger an rclone VFS cache refresh so newly written files become
visible immediately without waiting for --dir-cache-time to expire.

Requires the rclone mount service to be started with:
  --rc
  --rc-addr localhost:5572
  --rc-no-auth
"""

import logging
import os

import httpx

logger = logging.getLogger(__name__)

RCLONE_RC_URL = os.getenv("RCLONE_RC_URL", "http://localhost:5572")


def refresh_vfs() -> None:
    """
    POST /vfs/refresh?recursive=true to the rclone RC endpoint.
    Logs a warning on failure but never raises — a cache miss is not fatal.
    """
    url = f"{RCLONE_RC_URL}/vfs/refresh"
    try:
        resp = httpx.post(url, params={"recursive": "true"}, timeout=10)
        resp.raise_for_status()
        logger.info("rclone VFS refreshed: %s", resp.json())
    except Exception as exc:
        logger.warning("rclone VFS refresh failed (non-fatal): %s", exc)
