"""
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


# ── ffprobe helpers ───────────────────────────────────────────────────────────

# Codecs we treat as "already efficient lossy" — re-encoding them degrades quality.
_SKIP_CODECS: frozenset[str] = frozenset({"opus", "aac"})  # aac = M4A container

# File extensions that map to skip-eligible codecs (fast pre-check before probing).
_SKIP_EXTENSIONS: frozenset[str] = frozenset({".opus", ".m4a"})

# Lossless source codecs — safe to encode at any target bitrate without extra loss.
_LOSSLESS_CODECS: frozenset[str] = frozenset({"flac", "alac", "pcm_s16le", "pcm_s24le",
                                               "pcm_s32le", "pcm_f32le", "wavpack", "ape"})


def probe(path: str) -> tuple[str, int]:
    """
    Return (codec_name, bitrate_kbps) for the first audio stream in *path*.
    codec_name is lower-case (e.g. "opus", "aac", "mp3", "flac").
    bitrate_kbps is 0 when ffprobe cannot determine it.
    """
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
            s = streams[0]
            codec = s.get("codec_name", "").lower()
            kbps  = int(s.get("bit_rate", 0)) // 1000
            return codec, kbps
    except Exception:
        pass
    return "", 0


def should_skip(codec: str, bitrate_kbps: int) -> bool:
    """
    Return True when a file should NOT be re-encoded.

    Rule: skip if the codec is already an efficient modern lossy format
    (OPUS or AAC/M4A). Re-encoding these always causes quality loss with
    no meaningful benefit, regardless of bitrate.
    """
    return codec.lower() in _SKIP_CODECS


def pick_bitrate(codec: str, src_bitrate_kbps: int, max_bitrate: int = 256) -> int:
    """
    Choose the output bitrate for a file that *will* be processed.

    Rules:
    - Lossless source  → cap at max_bitrate (encoding from lossless, safe to target lower)
    - Lossy source     → keep original bitrate (never downsample lossy-to-lossy)
    - Unknown bitrate  → fall back to max_bitrate
    """
    if src_bitrate_kbps <= 0:
        return max_bitrate
    if codec.lower() in _LOSSLESS_CODECS:
        return min(src_bitrate_kbps, max_bitrate)
    # Lossy source: preserve original bitrate, but never exceed max_bitrate
    # (in case someone has an absurdly high-bitrate lossy file).
    return min(src_bitrate_kbps, max_bitrate)


def _target_ext(path: str) -> str:
    return os.path.splitext(path)[1].lower()


# ── Main conversion ───────────────────────────────────────────────────────────

def convert(
    src: str,
    dest: str,
    codec: str = "libopus",
    target_bitrate: int = 256,
) -> None:
    """
    Convert *src* to *dest* using FFmpeg.

    Parameters
    ----------
    src            : path to the raw source file (any format ffmpeg understands)
    dest           : desired output path (extension determines container)
    codec          : FFmpeg audio codec string (default: libopus)
    target_bitrate : exact output bitrate in kbps — caller is responsible for
                     computing this via pick_bitrate() before calling convert()
    """
    dest_ext   = _target_ext(dest)
    src_ext    = _target_ext(src)

    # Stream-copy when already in the right container and bitrate; this path is
    # hit rarely now that should_skip() gates most same-format files upstream,
    # but kept as a safety net.
    src_codec, src_kbps = probe(src)
    can_copy   = (src_ext == dest_ext) and (src_kbps > 0) and (src_kbps <= target_bitrate)
    audio_opts = ["-c:a", "copy"] if can_copy else ["-c:a", codec, "-b:a", f"{target_bitrate}k"]

    cmd = [
        "ffmpeg", "-y",
        "-i", src,
        *audio_opts,
        # Preserve all existing metadata.
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
        target_bitrate,
    )

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed:\n{result.stderr[-1500:]}")