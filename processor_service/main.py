#!/usr/bin/env python3
"""
processor_service/main.py
─────────────────────────
Standalone audio-processing service.

Three run modes
───────────────
  poll (default)  — watch for new .album control files every POLL_INTERVAL s
                    and process albums whose needs_processing=true.
  --once          — one-shot pass over existing .album files, then exit.
  --sync          — full library sync: walk every album directory regardless
                    of whether a .album file exists, write/overwrite .album
                    based on the actual files found, then process any album
                    that needs it.  Files stay exactly where they are.

Workflow (per album, all modes)
───────────────────────────────
  1. List audio files in the album directory.
  2. Count files per extension; the most-frequent extension is the target
     format.
  3. If mixed extensions → needs_processing=true, else false.
  4. Write (or overwrite) the .album control file in place.
  5. If needs_processing=false → done.
  6. Convert every non-target file to the target format with FFmpeg,
     writing the output alongside the originals (same dir, same stem,
     new extension).
  7. Delete the originals that were converted.
  8. Overwrite .album with is_processed=true.

Configuration is read from the environment / .env file (see .env.example).
"""

import asyncio
import logging
import os
import sys
import tempfile
from collections import Counter
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
WORKER_THREADS: int = int(os.getenv("WORKER_THREADS", "2"))
FFMPEG_CODEC: str = os.getenv("FFMPEG_CODEC", "libopus")
FFMPEG_EXT: str = os.getenv("FFMPEG_EXT", ".opus")
FFMPEG_MAX_BITRATE = int(os.getenv("FFMPEG_MAX_BITRATE_KBPS", "256"))

# ── Imports (after env is loaded) ─────────────────────────────────────────────

from cloud import (          # noqa: E402
    find_album_control_files,
    find_album_dirs,
    list_audio_files_in_dir,
    read_album_file,
    write_album_file,
    download_file,
    upload_file,
    delete_file,
    sftp as _sftp_conn,
    SFTP_BASE,
    ALBUM_CONTROL_FILE,
    AUDIO_EXTENSIONS,
)
from ffmpeg_processor import convert, sanitize_tags, probe, should_skip, pick_bitrate  # noqa: E402

# ── State: skip albums already processed this session ────────────────────────

_processed: set[str] = set()


# ── Per-album handler ─────────────────────────────────────────────────────────


async def _handle_album(control_path: str, sem: asyncio.Semaphore) -> None:
    """Process one album identified by its .album control-file path."""
    async with sem:
        if control_path in _processed:
            return

        # ── Read control file ──────────────────────────────────────────────
        fields = await asyncio.to_thread(read_album_file, control_path)
        if not fields:
            logger.warning("Could not read %s — skipping", control_path)
            return

        if fields.get("needs_processing", "false").lower() != "true":
            logger.debug("Skipping %s (needs_processing=false)", control_path)
            _processed.add(control_path)
            return

        if fields.get("is_processed", "false").lower() == "true":
            logger.debug("Skipping %s (already processed)", control_path)
            _processed.add(control_path)
            return

        album_dir = str(PurePosixPath(control_path).parent)
        logger.info("Processing album: %s", album_dir)

        # ── List audio files and pick dominant extension ───────────────────
        remote_audio = await asyncio.to_thread(list_audio_files_in_dir, album_dir)
        if not remote_audio:
            logger.warning("No audio files found in %s — skipping", album_dir)
            _processed.add(control_path)
            return

        ext_counts: Counter[str] = Counter(
            PurePosixPath(p).suffix.lower() for p in remote_audio
        )
        target_ext, dominant_count = ext_counts.most_common(1)[0]
        total = len(remote_audio)

        logger.info(
            "Album %s: %d file(s) total, dominant format=%s (%d), others=%s",
            album_dir, total, target_ext, dominant_count,
            {k: v for k, v in ext_counts.items() if k != target_ext},
        )

        if len(ext_counts) == 1:
            # All files already in the same format — nothing to convert.
            logger.info("All files already %s — marking processed", target_ext)
            await asyncio.to_thread(
                write_album_file, control_path,
                {"needs_processing": "true", "is_processed": "true"},
            )
            _processed.add(control_path)
            return

        # ── Convert non-dominant files ─────────────────────────────────────
        files_to_convert = [
            p for p in remote_audio
            if PurePosixPath(p).suffix.lower() != target_ext
        ]

        any_failure = False
        for remote_src in files_to_convert:
            src_name = PurePosixPath(remote_src).name
            stem = PurePosixPath(remote_src).stem
            remote_dest = f"{album_dir}/{stem}{target_ext}"

            logger.info("Converting: %s → %s", src_name, stem + target_ext)

            with tempfile.TemporaryDirectory(prefix="proc_") as tmp:
                local_src = os.path.join(tmp, src_name)
                local_dest = os.path.join(tmp, stem + target_ext)

                # Download source
                try:
                    await asyncio.to_thread(download_file, remote_src, local_src)
                except Exception as exc:
                    logger.error("Download failed for %r: %s", remote_src, exc)
                    any_failure = True
                    continue

                # Probe codec and pick bitrate
                src_codec, src_kbps = await asyncio.to_thread(probe, local_src)

                # Map target extension to FFmpeg codec string
                codec_map = {
                    ".mp3":  "libmp3lame",
                    ".m4a":  "aac",
                    ".aac":  "aac",
                    ".flac": "flac",
                    ".ogg":  "libvorbis",
                    ".opus": "libopus",
                }
                codec = codec_map.get(target_ext, FFMPEG_CODEC)
                target_bitrate = pick_bitrate(src_codec, src_kbps, FFMPEG_MAX_BITRATE)

                try:
                    await asyncio.to_thread(
                        convert,
                        src=local_src,
                        dest=local_dest,
                        codec=codec,
                        target_bitrate=target_bitrate,
                    )
                except Exception as exc:
                    logger.error("FFmpeg failed for %r: %s", remote_src, exc)
                    any_failure = True
                    continue

                # Upload converted file to the same album directory
                try:
                    await asyncio.to_thread(upload_file, local_dest, remote_dest)
                    logger.info("Uploaded converted: %s", remote_dest)
                except Exception as exc:
                    logger.error("Upload failed for %r: %s", remote_dest, exc)
                    any_failure = True
                    continue

            # Delete the original non-target-format file
            await asyncio.to_thread(delete_file, remote_src)
            logger.info("Deleted original: %s", remote_src)

        # ── Overwrite .album with is_processed=true ────────────────────────
        if not any_failure:
            await asyncio.to_thread(
                write_album_file, control_path,
                {"needs_processing": "true", "is_processed": "true"},
            )
            logger.info("Marked as processed: %s", control_path)
        else:
            logger.warning(
                "Some conversions failed for %s — not marking is_processed=true",
                album_dir,
            )

        _processed.add(control_path)


# ── Poll loop ─────────────────────────────────────────────────────────────────


async def poll_loop() -> None:
    sem = asyncio.Semaphore(WORKER_THREADS)
    logger.info(
        "Processor started\n"
        "  host   : %s\n"
        "  base   : %s\n"
        "  poll   : every %ds",
        os.environ.get("SFTP_HOST", "?"), SFTP_BASE, POLL_INTERVAL,
    )

    while True:
        try:
            control_files = await asyncio.to_thread(find_album_control_files)
            logger.info("Polling: found %d .album file(s)", len(control_files))
            new = [f for f in control_files if f not in _processed]
            if new:
                logger.info("Queuing %d new album(s) …", len(new))
            tasks = [asyncio.create_task(_handle_album(f, sem)) for f in new]
            if tasks:
                await asyncio.gather(*tasks)
        except Exception as exc:
            logger.error("Poll error: %s", exc)

        await asyncio.sleep(POLL_INTERVAL)


# ── One-shot pass ─────────────────────────────────────────────────────────────


async def run_once() -> None:
    """Process every pending album currently on the SFTP server and exit."""
    sem = asyncio.Semaphore(WORKER_THREADS)
    logger.info("One-shot pass — base: %s", SFTP_BASE)
    control_files = await asyncio.to_thread(find_album_control_files)
    if not control_files:
        logger.info("No .album files found.")
        return
    logger.info("Found %d .album file(s) …", len(control_files))
    await asyncio.gather(*[asyncio.create_task(_handle_album(f, sem)) for f in control_files])
    logger.info("Done.")


# ── Full library sync ─────────────────────────────────────────────────────────

async def full_sync() -> None:
    """
    Walk every album directory under SFTP_BASE, unconditionally inspect the
    audio files present, write (or overwrite) the .album control file, then
    process any album that needs format unification.

    Nothing is moved — files stay exactly where they are.
    """
    sem = asyncio.Semaphore(WORKER_THREADS)
    logger.info("Full sync started — base: %s", SFTP_BASE)

    album_dirs = await asyncio.to_thread(find_album_dirs)
    if not album_dirs:
        logger.info("No album directories found under %s.", SFTP_BASE)
        return

    logger.info("Found %d album director(ies) to inspect.", len(album_dirs))

    async def _sync_one(album_dir: str) -> None:
        control_path = f"{album_dir}/{ALBUM_CONTROL_FILE}"

        # ── Inspect audio files in this directory ──────────────────────────
        remote_audio = await asyncio.to_thread(list_audio_files_in_dir, album_dir)
        if not remote_audio:
            logger.debug("No audio files in %s — skipping", album_dir)
            return

        ext_counts: Counter[str] = Counter(
            PurePosixPath(p).suffix.lower() for p in remote_audio
        )
        needs_processing = len(ext_counts) > 1

        logger.info(
            "Sync %s: %d file(s), formats=%s → needs_processing=%s",
            album_dir, len(remote_audio), dict(ext_counts), needs_processing,
        )

        # ── Write / overwrite .album file ──────────────────────────────────
        # Always rewrite so the file reflects the current state of the folder,
        # even if one already existed (it may be stale after manual edits).
        await asyncio.to_thread(
            write_album_file, control_path,
            {
                "needs_processing": "true" if needs_processing else "false",
                "is_processed": "false",
            },
        )

        if not needs_processing:
            logger.info("Album %s is uniform — no conversion needed.", album_dir)
            return

        # ── Hand off to the normal per-album handler ───────────────────────
        # _handle_album will re-read the .album file we just wrote, so it will
        # see needs_processing=true and is_processed=false and proceed.
        await _handle_album(control_path, sem)

    tasks = [asyncio.create_task(_sync_one(d)) for d in album_dirs]
    await asyncio.gather(*tasks)
    logger.info("Full sync complete.")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Audio processor service")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--once",
        action="store_true",
        help="Process all albums that have a pending .album file, then exit.",
    )
    mode.add_argument(
        "--sync",
        action="store_true",
        help=(
            "Full library sync: inspect every album directory, write/overwrite "
            ".album files based on actual contents, convert where needed, then exit. "
            "Files are never moved."
        ),
    )
    args = parser.parse_args()

    try:
        if args.sync:
            asyncio.run(full_sync())
        elif args.once:
            asyncio.run(run_once())
        else:
            asyncio.run(poll_loop())
    except KeyboardInterrupt:
        logger.info("Shutting down …")
    finally:
        _sftp_conn.close()
