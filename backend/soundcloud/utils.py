import re
import sys
import subprocess


def log(msg: str) -> None:
    print(f"[soundcloud] {msg}", flush=True)


def warn(msg: str) -> None:
    print(f"[WARN] {msg}", file=sys.stderr, flush=True)


def die(msg: str) -> None:
    print(f"[ERROR] {msg}", file=sys.stderr)
    sys.exit(1)


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def safe_name(s: str) -> str:
    """Strip characters that are illegal in directory / file names."""
    return re.sub(r'[\\/*?:"<>|]', "_", s).strip()
