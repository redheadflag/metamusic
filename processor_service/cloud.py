"""
processor_service/cloud.py
──────────────────────────
SFTP transport layer (paramiko).

Layout on the remote machine
─────────────────────────────
  <SFTP_BASE>/
  └── Artist/
      └── Album/
          ├── 01 Track.m4a
          ├── 02 Track.opus
          ├── cover.jpg
          └── .album          ← control file written by backend

The .album file contains key=value pairs:
    needs_processing=true|false
    is_processed=true|false

The processor reads .album first. If needs_processing=false it skips the
album entirely. Otherwise it converts non-dominant-extension files, then
rewrites .album with is_processed=true in place.

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
SFTP_BASE: str = os.environ["SFTP_BASE"].rstrip("/")

SFTP_KEY_FILE: str | None = os.getenv("SFTP_KEY_FILE")
SFTP_PASSWORD: str | None = os.getenv("SFTP_PASSWORD")

ALBUM_CONTROL_FILE = ".album"
AUDIO_EXTENSIONS: frozenset[str] = frozenset(
    {".mp3", ".flac", ".ogg", ".m4a", ".wav", ".aiff", ".aif", ".opus", ".weba", ".webm"}
)


# ── Persistent connection ─────────────────────────────────────────────────────


class SFTPConnection:
    """
    Lazy, auto-reconnecting SFTP connection.
    A single instance is kept alive for the lifetime of the process.
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
            # password=SFTP_PASSWORD,
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

    # ── Public helpers ────────────────────────────────────────────────────────

    def find_album_control_files(self) -> list[str]:
        """
        Recursively walk SFTP_BASE and return every path that ends with
        ALBUM_CONTROL_FILE (.album).  These are the trigger points for the
        processor — one per album directory.
        """
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
                    elif entry.filename == ALBUM_CONTROL_FILE:
                        found.append(full)

            _walk(SFTP_BASE)
            return found

    def find_album_dirs(self) -> list[str]:
        """
        Recursively walk SFTP_BASE and return every directory that contains
        at least one audio file (leaf album folders).  Used by full_sync to
        discover albums that may not yet have a .album control file.
        """
        with self._lock:
            sftp = self._ensure()
            album_dirs: list[str] = []

            def _walk(remote_dir: str) -> None:
                try:
                    entries = sftp.listdir_attr(remote_dir)
                except IOError:
                    return
                has_audio = False
                for entry in entries:
                    if stat.S_ISDIR(entry.st_mode):
                        _walk(f"{remote_dir}/{entry.filename}")
                    elif PurePosixPath(entry.filename).suffix.lower() in AUDIO_EXTENSIONS:
                        has_audio = True
                if has_audio:
                    album_dirs.append(remote_dir)

            _walk(SFTP_BASE)
            return album_dirs

    def list_audio_files_in_dir(self, remote_dir: str) -> list[str]:
        """Return all audio file paths directly inside *remote_dir* (non-recursive)."""
        with self._lock:
            sftp = self._ensure()
            try:
                entries = sftp.listdir_attr(remote_dir)
            except IOError:
                return []
            return [
                f"{remote_dir}/{e.filename}"
                for e in entries
                if not stat.S_ISDIR(e.st_mode)
                and PurePosixPath(e.filename).suffix.lower() in AUDIO_EXTENSIONS
            ]

    def read_text_file(self, remote_path: str) -> str:
        """Download a small text file and return its contents as a string."""
        with self._lock:
            sftp = self._ensure()
            with sftp.open(remote_path, "r") as fh:
                return fh.read().decode("utf-8")

    def write_text_file(self, remote_path: str, content: str) -> None:
        """Overwrite *remote_path* with *content* (UTF-8)."""
        with self._lock:
            sftp = self._ensure()
            with sftp.open(remote_path, "w") as fh:
                fh.write(content.encode("utf-8"))

    def download(self, remote_path: str, local_path: str) -> None:
        with self._lock:
            sftp = self._ensure()
            sftp.get(remote_path, local_path)

    def upload(self, local_path: str, remote_path: str) -> None:
        with self._lock:
            sftp = self._ensure()
            self._makedirs(sftp, str(PurePosixPath(remote_path).parent))
            sftp.put(local_path, remote_path)

    def delete(self, remote_path: str) -> None:
        with self._lock:
            sftp = self._ensure()
            sftp.remove(remote_path)

    def close(self) -> None:
        self._close_quietly()


# Module-level singleton
sftp = SFTPConnection()


# ── Public API ────────────────────────────────────────────────────────────────

def find_album_control_files() -> list[str]:
    """Return all .album control file paths under SFTP_BASE."""
    return sftp.find_album_control_files()


def find_album_dirs() -> list[str]:
    """
    Return all directories under SFTP_BASE that contain at least one audio
    file.  Used by full_sync to discover albums without a .album file yet.
    """
    return sftp.find_album_dirs()


def list_audio_files_in_dir(remote_dir: str) -> list[str]:
    """Return all audio file paths directly inside *remote_dir*."""
    return sftp.list_audio_files_in_dir(remote_dir)


def read_album_file(control_path: str) -> dict[str, str]:
    """
    Parse a .album control file and return a dict of key→value strings.
    Lines that are blank or lack '=' are ignored.
    """
    try:
        raw = sftp.read_text_file(control_path)
    except Exception as exc:
        logger.warning("Could not read %s: %s", control_path, exc)
        return {}
    result: dict[str, str] = {}
    for line in raw.splitlines():
        line = line.strip()
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        result[key.strip()] = val.strip()
    return result


def write_album_file(control_path: str, fields: dict[str, str]) -> None:
    """Overwrite the .album control file at *control_path* with *fields*."""
    content = "".join(f"{k}={v}\n" for k, v in fields.items())
    sftp.write_text_file(control_path, content)


def download_file(remote_path: str, local_path: str) -> None:
    sftp.download(remote_path, local_path)


def upload_file(local_path: str, remote_path: str) -> None:
    sftp.upload(local_path, remote_path)


def delete_file(remote_path: str) -> None:
    """Delete a remote file, ignoring missing-file errors."""
    try:
        sftp.delete(remote_path)
    except (IOError, OSError):
        pass
