"""
processor_service/cloud.py
──────────────────────────
SFTP transport layer (paramiko).

Layout on the remote machine
─────────────────────────────
  <SFTP_BASE>/
  ├── unprocessed/          ← backend writes raw files here  (input)
  │   └── Artist/Album/...
  └── Artist/Album/...      ← processor writes finished files (output)

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
import stat
import threading
from pathlib import PurePosixPath

import paramiko  # type: ignore

logger = logging.getLogger("processor.sftp")

# ── Config ────────────────────────────────────────────────────────────────────

SFTP_HOST: str = os.environ["SFTP_HOST"]
SFTP_PORT: int = int(os.getenv("SFTP_PORT", "22"))
SFTP_USER: str = os.environ["SFTP_USER"]
SFTP_BASE: str = os.environ["SFTP_BASE"].rstrip("/")  # e.g. /home/user/music

SFTP_KEY_FILE: str | None = os.getenv("SFTP_KEY_FILE")
SFTP_PASSWORD: str | None = os.getenv("SFTP_PASSWORD")

# Derived paths
INPUT_DIR: str = f"{SFTP_BASE}/unprocessed"  # read raw files from here
OUTPUT_DIR: str = SFTP_BASE  # write processed files here


# ── Persistent connection ─────────────────────────────────────────────────────


class SFTPConnection:
    """
    Lazy, auto-reconnecting SFTP connection.
    A single instance is kept alive for the lifetime of the process;
    if the connection drops it is transparently re-established on the
    next operation.
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
        """Return a live SFTPClient, reconnecting if necessary."""
        if self._sftp is None:
            self._connect()
            return self._sftp  # type: ignore

        # Cheap liveness probe
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

    # ── Public helpers ────────────────────────────────────────────────────────

    def list_input_files(self) -> list[str]:
        """
        Recursively list all files under INPUT_DIR.
        Returns absolute remote paths.
        """
        # Hold the lock for the entire walk — _walk uses the sftp handle
        # and must not run concurrently with other operations.
        with self._lock:
            sftp = self._ensure()
            found: list[str] = []

            def _walk(remote_dir: str) -> None:
                try:
                    entries = sftp.listdir_attr(remote_dir)
                except IOError:
                    return
                for entry in entries:
                    full = f"{remote_dir}/{entry.filename}"
                    if stat.S_ISDIR(entry.st_mode):
                        _walk(full)
                    else:
                        found.append(full)

            _walk(INPUT_DIR)
            return found

    def download(self, remote_path: str, local_path: str) -> None:
        """Download a single file from the remote to *local_path*."""
        with self._lock:
            sftp = self._ensure()
            sftp.get(remote_path, local_path)

    def upload(self, local_path: str, remote_path: str) -> None:
        """
        Upload *local_path* to *remote_path*, creating any missing
        parent directories on the remote.
        """
        with self._lock:
            sftp = self._ensure()
            self._makedirs(sftp, str(PurePosixPath(remote_path).parent))
            sftp.put(local_path, remote_path)

    def delete(self, remote_path: str) -> None:
        """Remove a file from the remote."""
        with self._lock:
            sftp = self._ensure()
            sftp.remove(remote_path)

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

    def close(self) -> None:
        self._close_quietly()


# Module-level singleton — imported by main.py
sftp = SFTPConnection()


# ── Public API (called by main.py) ────────────────────────────────────────────


def list_input_files() -> list[str]:
    """Return all remote file paths under INPUT_DIR."""
    return sftp.list_input_files()


def download_file(remote_path: str, local_path: str) -> None:
    """Download *remote_path* to *local_path*."""
    sftp.download(remote_path, local_path)


def upload_file(local_path: str, remote_path: str) -> None:
    """Upload *local_path* to *remote_path*, creating parent dirs as needed."""
    sftp.upload(local_path, remote_path)


def delete_input_file(remote_path: str) -> None:
    """Delete a raw file from INPUT_DIR after successful processing."""
    sftp.delete(remote_path)


def delete_output_file_if_exists(remote_path: str) -> None:
    """Delete *remote_path* from the output tree, ignoring missing-file errors.
    Used to remove stale same-stem files (e.g. old .m4a) before uploading
    the newly converted version (e.g. .opus).
    """
    try:
        sftp.delete(remote_path)
    except (IOError, OSError):
        pass  # already gone — that's fine


def input_to_output_path(remote_input_path: str, new_ext: str) -> str:
    """
    Derive the output path from an input path.

    Example:
        input:  /home/user/music/unprocessed/Artist/Album/01 Track.flac
        output: /home/user/music/Artist/Album/01 Track.mp3
    """
    rel = PurePosixPath(remote_input_path).relative_to(INPUT_DIR)
    return str(PurePosixPath(OUTPUT_DIR) / rel.with_suffix(new_ext))
