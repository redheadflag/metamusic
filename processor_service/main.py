#!/usr/bin/env python3
"""
processor_service/main.py
─────────────────────────
Standalone audio-processing service.

Workflow (per file):
  1. Poll sftp://<host>/<SFTP_BASE>/unprocessed/ for new audio files.
  2. Download each file to a local temp directory.
  3. Run FFmpeg to convert (e.g. FLAC → MP3) and preserve metadata.
  4. Upload the finished file to sftp://<host>/<SFTP_BASE>/<Artist>/<Album>/
     (mirrors the input tree, but one level up — outside "unprocessed").
  5. Delete the raw source from the "unprocessed" folder.

Configuration is read from the environment / .env file (see .env.example).
"""

import asyncio
import logging
import os
import sys
import tempfile
from pathlib import Path, PurePosixPath

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("processor")

# ── Config ────────────────────────────────────────────────────────────────────

POLL_INTERVAL: int   = int(os.getenv("POLL_INTERVAL_SECONDS", "30"))
DELETE_SOURCE: bool  = os.getenv("DELETE_SOURCE_AFTER_PROCESSING", "true").lower() == "true"
WORKER_THREADS: int  = int(os.getenv("WORKER_THREADS", "2"))
FFMPEG_CODEC: str    = os.getenv("FFMPEG_CODEC", "libmp3lame")
FFMPEG_EXT: str      = os.getenv("FFMPEG_EXT", ".mp3")
FFMPEG_MAX_BITRATE   = int(os.getenv("FFMPEG_MAX_BITRATE_KBPS", "256"))

AUDIO_EXTENSIONS: frozenset[str] = frozenset(
    {".mp3", ".flac", ".ogg", ".m4a", ".wav", ".aiff", ".aif", ".opus", ".weba", ".webm"}
)

# ── Imports (after env is loaded) ─────────────────────────────────────────────

from cloud import (          # noqa: E402
    list_input_files,
    download_file,
    upload_file,
    delete_input_file,
    input_to_output_path,
    sftp as _sftp_conn,
)
from ffmpeg_processor import convert  # noqa: E402

# ── State: skip files already processed this session ─────────────────────────

_processed: set[str] = set()


# ── Per-file handler ──────────────────────────────────────────────────────────

async def _handle_file(remote_input: str, sem: asyncio.Semaphore) -> None:
    async with sem:
        if remote_input in _processed:
            return

        ext = PurePosixPath(remote_input).suffix.lower()
        if ext not in AUDIO_EXTENSIONS:
            return

        logger.info("Found: %s", remote_input)

        with tempfile.TemporaryDirectory(prefix="proc_") as tmp:
            src_name  = PurePosixPath(remote_input).name
            local_src = os.path.join(tmp, src_name)

            # 1 — Download raw file
            try:
                await asyncio.to_thread(download_file, remote_input, local_src)
                logger.info("Downloaded: %s", src_name)
            except Exception as exc:
                logger.error("Download failed for %r: %s", remote_input, exc)
                return

            # 2 — Convert with FFmpeg
            local_dest = os.path.join(tmp, PurePosixPath(src_name).stem + FFMPEG_EXT)
            try:
                await asyncio.to_thread(
                    convert,
                    src=local_src,
                    dest=local_dest,
                    codec=FFMPEG_CODEC,
                    max_bitrate=FFMPEG_MAX_BITRATE,
                )
            except Exception as exc:
                logger.error("FFmpeg failed for %r: %s", remote_input, exc)
                return

            # 3 — Upload to output path on the same SFTP server
            remote_output = input_to_output_path(remote_input, FFMPEG_EXT)
            try:
                await asyncio.to_thread(upload_file, local_dest, remote_output)
                logger.info("Uploaded: %s", remote_output)
            except Exception as exc:
                logger.error("Upload failed for %r: %s", remote_output, exc)
                return

        # 4 — Mark done and optionally remove the raw source
        _processed.add(remote_input)

        if DELETE_SOURCE:
            try:
                await asyncio.to_thread(delete_input_file, remote_input)
                logger.info("Deleted source: %s", remote_input)
            except Exception as exc:
                logger.warning("Could not delete source %r: %s", remote_input, exc)


# ── Poll loop ─────────────────────────────────────────────────────────────────

async def poll_loop() -> None:
    from cloud import INPUT_DIR, OUTPUT_DIR, SFTP_HOST
    sem = asyncio.Semaphore(WORKER_THREADS)
    logger.info(
        "Processor started\n"
        "  host   : %s\n"
        "  input  : %s\n"
        "  output : %s\n"
        "  poll   : every %ds",
        SFTP_HOST, INPUT_DIR, OUTPUT_DIR, POLL_INTERVAL,
    )

    while True:
        try:
            files = await asyncio.to_thread(list_input_files)
            new   = [f for f in files if f not in _processed]
            if new:
                logger.info("Queuing %d new file(s) …", len(new))
            tasks = [asyncio.create_task(_handle_file(f, sem)) for f in new]
            if tasks:
                await asyncio.gather(*tasks)
        except Exception as exc:
            logger.error("Poll error: %s", exc)

        await asyncio.sleep(POLL_INTERVAL)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process all files currently in unprocessed/ and exit (no polling).",
    )
    args = parser.parse_args()

    try:
        asyncio.run(run_once() if args.once else poll_loop())
    except KeyboardInterrupt:
        logger.info("Shutting down …")
    finally:
        _sftp_conn.close()


# ── One-shot pass ─────────────────────────────────────────────────────────────

async def run_once() -> None:
    """Process every file currently in unprocessed/ and exit."""
    from cloud import INPUT_DIR, OUTPUT_DIR, SFTP_HOST
    sem = asyncio.Semaphore(WORKER_THREADS)
    logger.info(
        "One-shot pass\n"
        "  host   : %s\n"
        "  input  : %s\n"
        "  output : %s",
        SFTP_HOST, INPUT_DIR, OUTPUT_DIR,
    )
    files = await asyncio.to_thread(list_input_files)
    if not files:
        logger.info("Nothing to process.")
        return
    logger.info("Processing %d file(s) …", len(files))
    await asyncio.gather(*[asyncio.create_task(_handle_file(f, sem)) for f in files])
    logger.info("Done.")