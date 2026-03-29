"""
backend/services/sftp.py
────────────────────────
SFTP transport layer for the backend service (paramiko).

The backend writes files directly into the album folder under SFTP_BASE.
A .album control file is written alongside the tracks so the processor
service knows whether format conversion is needed.

Remote layout
─────────────
  <SFTP_BASE>/
  └── Artist/
      └── Album/
          ├── 01 Track.m4a
          ├── cover.jpg
          └── .album        ← needs_processing / is_processed flags

.env variables
──────────────
  SFTP_HOST      remote hostname or IP
  SFTP_PORT      (optional, default 22)
  SFTP_USER      login username
  SFTP_KEY_FILE  path to private key  (preferred)
  SFTP_PASSWORD  password             (fallback)
  SFTP_BASE      absolute path on the remote, e.g. /home/user/music
"""

import logging
import os
import threading
from pathlib import PurePosixPath

import paramiko

logger = logging.getLogger(__name__)

SFTP_HOST: str = os.environ["SFTP_HOST"]
SFTP_PORT: int = int(os.getenv("SFTP_PORT", "22"))
SFTP_USER: str = os.environ["SFTP_USER"]
SFTP_BASE: str = os.environ["SFTP_BASE"].rstrip("/")
SFTP_KEY_FILE: str | None = os.getenv("SFTP_KEY_FILE")
SFTP_PASSWORD: str | None = os.getenv("SFTP_PASSWORD")


class SFTPConnection:
    """
    Lazy, auto-reconnecting SFTP connection.
    One instance is kept alive for the lifetime of the process;
    dropped connections are transparently re-established.
    """

    def __init__(self) -> None:
        self._ssh: paramiko.SSHClient | None = None
        self._sftp: paramiko.SFTPClient | None = None
        self._lock = threading.Lock()

    def _connect(self) -> None:
        logger.info("SFTP connecting to %s@%s:%d …", SFTP_USER, SFTP_HOST, SFTP_PORT)
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(
            hostname=SFTP_HOST,
            port=SFTP_PORT,
            username=SFTP_USER,
            key_filename=SFTP_KEY_FILE,
            password=SFTP_PASSWORD,
            timeout=15,
        )
        self._ssh = ssh
        self._sftp = ssh.open_sftp()
        logger.info("SFTP connected.")

    def _ensure(self) -> paramiko.SFTPClient:
        if self._sftp is None:
            self._connect()
            return self._sftp  # type: ignore
        try:
            self._sftp.stat(SFTP_BASE)  # type: ignore
        except (OSError, EOFError, paramiko.SSHException):
            logger.warning("SFTP connection lost — reconnecting …")
            self._close_quietly()
            self._connect()
        return self._sftp  # type: ignore

    def _close_quietly(self) -> None:
        for obj in (self._sftp, self._ssh):
            try:
                if obj:
                    obj.close()
            except Exception:
                pass
        self._sftp = None
        self._ssh = None

    def _makedirs(self, sftp: paramiko.SFTPClient, remote_dir: str) -> None:
        """Recursively create *remote_dir* if it does not exist."""
        parts = PurePosixPath(remote_dir).parts
        current = ""
        for part in parts:
            current = f"{current}/{part}" if current else part
            if current == "/":
                continue
            try:
                sftp.stat(current)
            except IOError:
                sftp.mkdir(current)

    def upload(self, local_path: str, remote_path: str) -> None:
        """Upload *local_path* to *remote_path*, creating parent dirs as needed."""
        with self._lock:
            sftp = self._ensure()
            self._makedirs(sftp, str(PurePosixPath(remote_path).parent))
            sftp.put(local_path, remote_path)
            logger.info("SFTP uploaded: %s → %s", local_path, remote_path)

    def close(self) -> None:
        self._close_quietly()


# Module-level singleton
_conn = SFTPConnection()


def album_path(album_artist: str, album: str, filename: str) -> str:
    """
    Build the remote path for a file directly in the album folder.

      → <SFTP_BASE>/<album_artist>/<album>/<filename>
    """
    return str(PurePosixPath(SFTP_BASE) / album_artist / album / filename)


def upload_file(local_path: str, remote_path: str) -> None:
    """Upload a local file to an absolute remote path under SFTP_BASE."""
    _conn.upload(local_path, remote_path)


def upload_cover(cover_bytes: bytes, album_artist: str, album: str) -> str:
    """
    Write *cover_bytes* as ``cover.jpg`` directly into the album folder.

      → <SFTP_BASE>/<album_artist>/<album>/cover.jpg

    Returns the remote path on success, empty string on failure (non-fatal).
    """
    import tempfile
    remote_path = album_path(album_artist, album, "cover.jpg")
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".jpg")
    try:
        import os

        os.write(tmp_fd, cover_bytes)
        os.close(tmp_fd)
        _conn.upload(tmp_path, remote_path)
        return remote_path
    except Exception as exc:
        logger.warning("Could not upload cover.jpg: %s", exc)
        return ""
    finally:
        try:
            import os as _os

            _os.unlink(tmp_path)
        except OSError:
            pass


def write_album_file(album_artist: str, album: str, needs_processing: bool) -> str:
    """
    Write a ``.album`` control file into the album folder.

    Format (key=value, one per line)::

        needs_processing=true
        is_processed=false

    ``needs_processing`` is True when the album contains files with more than
    one distinct audio extension (mixed formats that the processor must unify).
    ``is_processed`` is always written as ``false`` by the backend; the
    processor service flips it to ``true`` once it finishes.

    Returns the remote path on success, empty string on failure (non-fatal).
    """
    import tempfile
    content = (
        f"needs_processing={'true' if needs_processing else 'false'}\n"
        "is_processed=false\n"
    ).encode()
    remote_path = album_path(album_artist, album, ".album")
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".album")
    try:
        import os
        os.write(tmp_fd, content)
        os.close(tmp_fd)
        _conn.upload(tmp_path, remote_path)
        logger.info(
            "Wrote .album file: needs_processing=%s → %s",
            needs_processing, remote_path,
        )
        return remote_path
    except Exception as exc:
        logger.warning("Could not write .album file: %s", exc)
        return ""
    finally:
        try:
            import os as _os
            _os.unlink(tmp_path)
        except OSError:
            pass


def close() -> None:
    _conn.close()
