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
from pathlib import PurePosixPath

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("processor")

# ── Config ────────────────────────────────────────────────────────────────────

POLL_INTERVAL: int = int(os.getenv("POLL_INTERVAL_SECONDS", "5"))
DELETE_SOURCE: bool = (
    os.getenv("DELETE_SOURCE_AFTER_PROCESSING", "true").lower() == "true"
)
WORKER_THREADS: int = int(os.getenv("WORKER_THREADS", "2"))
FFMPEG_CODEC: str = os.getenv("FFMPEG_CODEC", "libopus")
FFMPEG_EXT: str = os.getenv("FFMPEG_EXT", ".opus")
FFMPEG_MAX_BITRATE = int(os.getenv("FFMPEG_MAX_BITRATE_KBPS", "256"))

AUDIO_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".mp3",
        ".flac",
        ".ogg",
        ".m4a",
        ".wav",
        ".aiff",
        ".aif",
        ".opus",
        ".weba",
        ".webm",
    }
)

# ── Imports (after env is loaded) ─────────────────────────────────────────────

from cloud import (  # noqa: E402
    list_input_files,
    download_file,
    upload_file,
    delete_input_file,
    delete_output_file_if_exists,
    input_to_output_path,
    sftp as _sftp_conn,
)
from ffmpeg_processor import (
    convert,
    sanitize_tags,
    extract_cover,
    probe,
    should_skip,
    pick_bitrate,
)  # noqa: E402

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
            src_name = PurePosixPath(remote_input).name
            local_src = os.path.join(tmp, src_name)

            # 1 — Download raw file
            try:
                await asyncio.to_thread(download_file, remote_input, local_src)
                logger.info("Downloaded: %s", src_name)
            except Exception as exc:
                logger.error("Download failed for %r: %s", remote_input, exc)
                return

            # 2 — Probe and decide whether to process
            src_codec, src_kbps = await asyncio.to_thread(probe, local_src)
            if should_skip(src_codec, src_kbps):
                logger.info(
                    "Skipping re-encode for %s — already %s at %d kbps; fixing tags only",
                    src_name,
                    src_codec,
                    src_kbps,
                )
                src_suffix = PurePosixPath(remote_input).suffix
                # Must differ from local_src — FFmpeg refuses to overwrite its own input.
                local_dest = os.path.join(
                    tmp, PurePosixPath(src_name).stem + "_clean" + src_suffix
                )
                remote_output = input_to_output_path(remote_input, src_suffix)
                try:
                    await asyncio.to_thread(sanitize_tags, local_src, local_dest)
                except Exception as exc:
                    logger.error("Tag sanitize failed for %r: %s", remote_input, exc)
                    return
                # Extract cover art to a cover.jpg alongside the output track.
                remote_cover = input_to_output_path(remote_input, ".jpg")
                remote_cover_dir = str(PurePosixPath(remote_cover).parent)
                local_cover = os.path.join(tmp, "cover.jpg")
                cover_ok = await asyncio.to_thread(extract_cover, local_src, tmp)
                if cover_ok:
                    remote_cover_path = remote_cover_dir + "/cover.jpg"
                    try:
                        await asyncio.to_thread(
                            upload_file, local_cover, remote_cover_path
                        )
                        logger.info("Uploaded cover art: %s", remote_cover_path)
                    except Exception as exc:
                        logger.warning(
                            "Cover upload failed for %r: %s", remote_cover_path, exc
                        )
                try:
                    await asyncio.to_thread(upload_file, local_dest, remote_output)
                    logger.info(
                        "Moved (tag-fixed, no re-encode): %s → %s",
                        remote_input,
                        remote_output,
                    )
                except Exception as exc:
                    logger.error("Move failed for %r: %s", remote_input, exc)
                    return

                _processed.add(remote_input)

                if DELETE_SOURCE:
                    try:
                        await asyncio.to_thread(delete_input_file, remote_input)
                        logger.info("Deleted source: %s", remote_input)
                    except Exception as exc:
                        logger.warning(
                            "Could not delete source %r: %s", remote_input, exc
                        )

                return

            target_bitrate = pick_bitrate(src_codec, src_kbps, FFMPEG_MAX_BITRATE)
            logger.info(
                "Processing %s — codec=%s, src=%d kbps → target=%d kbps",
                src_name,
                src_codec,
                src_kbps,
                target_bitrate,
            )

            # 3 — Convert with FFmpeg
            local_dest = os.path.join(tmp, PurePosixPath(src_name).stem + FFMPEG_EXT)
            try:
                await asyncio.to_thread(
                    convert,
                    src=local_src,
                    dest=local_dest,
                    codec=FFMPEG_CODEC,
                    target_bitrate=target_bitrate,
                )
            except Exception as exc:
                logger.error("FFmpeg failed for %r: %s", remote_input, exc)
                return

            # 4 — Extract cover art and upload to output album directory
            remote_output = input_to_output_path(remote_input, FFMPEG_EXT)
            remote_cover_dir = str(PurePosixPath(remote_output).parent)
            local_cover = os.path.join(tmp, "cover.jpg")
            cover_ok = await asyncio.to_thread(extract_cover, local_src, tmp)
            if cover_ok:
                remote_cover_path = remote_cover_dir + "/cover.jpg"
                try:
                    await asyncio.to_thread(upload_file, local_cover, remote_cover_path)
                    logger.info("Uploaded cover art: %s", remote_cover_path)
                except Exception as exc:
                    logger.warning(
                        "Cover upload failed for %r: %s", remote_cover_path, exc
                    )
            # Remove any stale same-stem file with a different extension
            # (e.g. old .m4a left over before we started converting to .opus).
            for stale_ext in (
                ".m4a",
                ".mp3",
                ".flac",
                ".ogg",
                ".wav",
                ".aiff",
                ".aif",
                ".weba",
                ".webm",
            ):
                if stale_ext == FFMPEG_EXT:
                    continue
                stale = input_to_output_path(remote_input, stale_ext)
                await asyncio.to_thread(delete_output_file_if_exists, stale)
            # Upload converted track
            try:
                await asyncio.to_thread(upload_file, local_dest, remote_output)
                logger.info("Uploaded: %s", remote_output)
            except Exception as exc:
                logger.error("Upload failed for %r: %s", remote_output, exc)
                return

        # 5 — Mark done and optionally remove the raw source
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
        SFTP_HOST,
        INPUT_DIR,
        OUTPUT_DIR,
        POLL_INTERVAL,
    )

    # Poll immediately on startup, then wait POLL_INTERVAL between subsequent polls.
    while True:
        try:
            files = await asyncio.to_thread(list_input_files)
            logger.info("Polling: found %d file(s) in unprocessed/", len(files))
            new = [f for f in files if f not in _processed]
            if new:
                logger.info("Queuing %d new file(s) …", len(new))
            tasks = [asyncio.create_task(_handle_file(f, sem)) for f in new]
            if tasks:
                await asyncio.gather(*tasks)
        except Exception as exc:
            logger.error("Poll error: %s", exc)

        await asyncio.sleep(POLL_INTERVAL)


# ── One-shot pass ─────────────────────────────────────────────────────────────


async def run_once() -> None:
    """Process every file currently in unprocessed/ and exit."""
    from cloud import INPUT_DIR, OUTPUT_DIR, SFTP_HOST

    sem = asyncio.Semaphore(WORKER_THREADS)
    logger.info(
        "One-shot pass\n  host   : %s\n  input  : %s\n  output : %s",
        SFTP_HOST,
        INPUT_DIR,
        OUTPUT_DIR,
    )
    files = await asyncio.to_thread(list_input_files)
    if not files:
        logger.info("Nothing to process.")
        return
    logger.info("Processing %d file(s) …", len(files))
    await asyncio.gather(*[asyncio.create_task(_handle_file(f, sem)) for f in files])
    logger.info("Done.")


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
