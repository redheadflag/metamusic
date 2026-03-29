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

logger = logging.getLogger(__name__)


# ── ffprobe helpers ───────────────────────────────────────────────────────────

# Codecs we treat as "already in the target format" — only Opus, since that
# is the output codec.  AAC/M4A is intentionally NOT skipped: M4A files must
# be transcoded to Opus so every track in an album lands in the same format
# and Navidrome groups them into a single album entry.
_SKIP_CODECS: frozenset[str] = frozenset({"opus"})

# File extensions that map to skip-eligible codecs (fast pre-check before probing).
_SKIP_EXTENSIONS: frozenset[str] = frozenset({".opus"})

# Lossless source codecs — safe to encode at any target bitrate without extra loss.
_LOSSLESS_CODECS: frozenset[str] = frozenset(
    {
        "flac",
        "alac",
        "pcm_s16le",
        "pcm_s24le",
        "pcm_s32le",
        "pcm_f32le",
        "wavpack",
        "ape",
    }
)


def probe(path: str) -> tuple[str, int]:
    """
    Return (codec_name, bitrate_kbps) for the first audio stream in *path*.
    codec_name is lower-case (e.g. "opus", "aac", "mp3", "flac").
    bitrate_kbps is 0 when ffprobe cannot determine it.

    M4A/AAC files store bitrate at the container (format) level rather than
    the stream level, so we fall back to the format-level bit_rate when the
    stream does not report one.
    """
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_streams",
                "-select_streams",
                "a:0",
                "-show_format",
                path,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        data = json.loads(result.stdout)
        streams = data.get("streams", [])
        fmt = data.get("format", {})
        if streams:
            s = streams[0]
            codec = s.get("codec_name", "").lower()
            # Prefer stream-level bitrate; fall back to format-level bitrate
            # (M4A stores it there) and finally to 0.
            kbps = int(s.get("bit_rate") or fmt.get("bit_rate") or 0) // 1000
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


# ── Cover art extraction ──────────────────────────────────────────────────────


def extract_cover(src: str, dest_dir: str) -> bool:
    """
    Extract the first embedded picture from *src* and save it as
    cover.jpg in *dest_dir*.  Returns True if a cover was written.

    We extract to a separate file rather than embedding in every track because:
      • The mjpeg streams in these M4A files have broken timescales that cause
        FFmpeg to hang when trying to copy them into a new container.
      • Navidrome reads cover.jpg / folder.jpg from the album directory
        automatically, and prefers it over per-track embedded art.
      • Writing once per album (skip if exists) is more efficient.
    """
    cover_path = os.path.join(dest_dir, "cover.jpg")
    if os.path.exists(cover_path):
        return True  # already extracted for this album dir

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        src,
        "-an",  # no audio
        "-vcodec",
        "copy",
        "-map",
        "0:v:0",
        cover_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if result.returncode == 0 and os.path.getsize(cover_path) > 0:
            logger.info("Extracted cover art → %s", cover_path)
            return True
    except Exception:
        pass
    # Clean up empty/failed file
    try:
        if os.path.exists(cover_path) and os.path.getsize(cover_path) == 0:
            os.remove(cover_path)
    except Exception:
        pass
    return False


# ── Tag-only sanitise pass (for skipped files) ────────────────────────────────


def sanitize_tags(src: str, dest: str) -> None:
    """
    Stream-copy *src* to *dest* with no re-encoding, but fix the tags that
    cause Navidrome to misread M4A files:

      • encoder=Lavf…  — Navidrome uses this to detect "raw mux" files and
                          falls back to a code-path that skips the duration
                          atom, so the track shows 0:00.  We blank it out.
      • album_artist   — explicitly re-written so the correct container atom
                          (iTunes aART vs Vorbis ALBUMARTIST) is present,
                          keeping the track in the right album alongside any
                          .opus siblings.

    This is intentionally a separate function from convert() so the caller
    (main.py skip-path) does not have to pretend it is doing a conversion.
    """
    dest_ext = _target_ext(dest)
    id3_opts = ["-id3v2_version", "3"] if dest_ext == ".mp3" else []

    # Read album_artist from source so we can re-embed it in the correct atom.
    album_artist_opts: list[str] = []
    try:
        probe_result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", src],
            capture_output=True,
            text=True,
            timeout=30,
        )
        tags = json.loads(probe_result.stdout).get("format", {}).get("tags", {})
        album_artist = next(
            (
                v
                for k, v in tags.items()
                if k.lower() in ("album_artist", "albumartist")
            ),
            None,
        )
        if album_artist:
            album_artist_opts = ["-metadata", f"album_artist={album_artist}"]
    except Exception:
        pass

    # Map audio stream only.  These M4A files carry an embedded cover art
    # as a mjpeg video stream with "timescale not set", which causes FFmpeg
    # to stall indefinitely when trying to copy or re-mux it.  We drop the
    # cover art here — Navidrome will fall back to folder.jpg/cover.jpg in
    # the same directory, which is the recommended layout anyway.
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        src,
        "-map",
        "0:a:0",  # audio only — skip broken cover-art stream
        "-c:a",
        "copy",
        "-map_metadata",
        "0",
        "-metadata",
        "encoder=",
        *album_artist_opts,
        *id3_opts,
        dest,
    ]

    logger.info(
        "sanitize_tags: %s -> %s (stream-copy, audio-only tag fix)",
        os.path.basename(src),
        os.path.basename(dest),
    )

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg tag sanitize failed:\n{result.stderr[-1500:]}")


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
    dest_ext = _target_ext(dest)
    src_ext = _target_ext(src)

    # Stream-copy when already in the right container and bitrate; this path is
    # hit rarely now that should_skip() gates most same-format files upstream,
    # but kept as a safety net.
    src_codec, src_kbps = probe(src)
    can_copy = (src_ext == dest_ext) and (src_kbps > 0) and (src_kbps <= target_bitrate)
    audio_opts = (
        ["-c:a", "copy"] if can_copy else ["-c:a", codec, "-b:a", f"{target_bitrate}k"]
    )

    # -id3v2_version 3 is only valid for MP3 (ID3 container).  Passing it for
    # M4A or Opus silently corrupts or drops tags — including the duration atom
    # in M4A — which is why Navidrome shows no duration and splits albums.
    id3_opts = ["-id3v2_version", "3"] if dest_ext == ".mp3" else []

    # Read only the tags Navidrome actually uses.  We do NOT use
    # -map_metadata 0 because M4A sources carry container-specific
    # junk (major_brand, compatible_brands, encoder=Lavf…, Telegram
    # comment, etc.) that pollutes the output and confuses Navidrome.
    # Cherry-picking gives us a clean, predictable tag set.
    _WANTED = (
        "title",
        "artist",
        "album",
        "album_artist",
        "albumartist",
        "track",
        "tracknumber",
        "disc",
        "discnumber",
        "date",
        "year",
        "genre",
        "composer",
        "lyrics",
    )
    meta_opts: list[str] = []
    try:
        probe_result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", src],
            capture_output=True,
            text=True,
            timeout=30,
        )
        tags = json.loads(probe_result.stdout).get("format", {}).get("tags", {})
        # Normalise keys to lower-case and keep only wanted tags.
        seen: set[str] = set()
        for k, v in tags.items():
            kl = k.lower()
            if kl not in _WANTED or kl in seen:
                continue
            seen.add(kl)
            # Normalise album_artist spelling so Navidrome always finds it.
            out_key = "album_artist" if kl in ("album_artist", "albumartist") else kl
            meta_opts += ["-metadata", f"{out_key}={v}"]
    except Exception:
        pass

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        src,
        "-map",
        "0:a:0",  # audio only — cover art written as cover.jpg separately
        *audio_opts,
        "-map_metadata",
        "-1",  # start with empty tags, then add only what we want
        *meta_opts,
        *id3_opts,
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
