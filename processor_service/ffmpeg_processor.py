"""
processor_service/ffmpeg_processor.py
──────────────────────────────────────
FFmpeg conversion logic extracted from the original backend processing.py.

Public function
───────────────
  convert(src, dest, codec, max_bitrate)

      • Probes the source bitrate with ffprobe.
      • If the source is already in the target format and within the bitrate
        limit, the audio stream is stream-copied (no re-encoding).
      • Otherwise re-encodes to the target codec at min(src_bitrate, max_bitrate).
      • Preserves all ID3 / Vorbis metadata tags already present in the file
        (unlike the backend which strips and rewrites them — here we keep
        whatever the backend embedded before uploading the raw file).
"""

import json
import logging
import os
import subprocess
import tempfile

logger = logging.getLogger(__name__)


# ── ffprobe helper ────────────────────────────────────────────────────────────

def _source_bitrate(path: str) -> int:
    """Return the audio stream bitrate in kbps, or 0 on failure."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-print_format", "json",
                "-show_streams", "-select_streams", "a:0",
                path,
            ],
            capture_output=True, text=True, timeout=30,
        )
        streams = json.loads(result.stdout).get("streams", [])
        if streams:
            return int(streams[0].get("bit_rate", 0)) // 1000
    except Exception:
        pass
    return 0


def _target_ext(path: str) -> str:
    return os.path.splitext(path)[1].lower()


# ── Main conversion ───────────────────────────────────────────────────────────

def convert(
    src: str,
    dest: str,
    codec: str = "libmp3lame",
    max_bitrate: int = 256,
) -> None:
    """
    Convert *src* to *dest* using FFmpeg.

    Parameters
    ----------
    src         : path to the raw source file (any format ffmpeg understands)
    dest        : desired output path (extension determines container)
    codec       : FFmpeg audio codec string (default: libmp3lame → MP3)
    max_bitrate : upper bitrate cap in kbps (default: 256)
    """
    src_kbps    = _source_bitrate(src)
    target_br   = min(src_kbps, max_bitrate) if src_kbps > 0 else max_bitrate

    dest_ext    = _target_ext(dest)
    src_ext     = _target_ext(src)

    # Stream-copy only when source extension matches destination and bitrate is
    # already within limit — avoids any generation loss for e.g. 192 kbps MP3.
    can_copy    = (src_ext == dest_ext) and (src_kbps > 0) and (src_kbps <= max_bitrate)
    audio_opts  = ["-c:a", "copy"] if can_copy else ["-c:a", codec, "-b:a", f"{target_br}k", "-q:a", "0"]

    cmd = [
        "ffmpeg", "-y",
        "-i", src,
        *audio_opts,
        # Preserve all existing metadata (tags were embedded by the backend
        # or carried over from the original file).
        "-map_metadata", "0",
        "-id3v2_version", "3",
        dest,
    ]

    logger.info(
        "ffmpeg: %s → %s  (%s, %d kbps → %d kbps)",
        os.path.basename(src),
        os.path.basename(dest),
        "copy" if can_copy else "encode",
        src_kbps,
        target_br,
    )

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed:\n{result.stderr[-1500:]}")
