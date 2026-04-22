"""
fix_artists
───────────
Sanitize audio files and split multi-value artist tags into native
multi-value tags.

Two independent fixes, both in-place (same path, atomic replace):

1. sanitize_m4a_streams(path)
   Some .m4a files (notably SoundCloud exports) contain the cover art as
   a full video stream with its own duration instead of an attached_pic.
   Players then show the video duration and the track duration is
   unreadable. We rewrite the container keeping one audio stream, the
   (optional) cover, and forcing the video disposition to attached_pic:

       ffmpeg -i src -map 0:a:0 -map 0:v:0 -c copy \
              -disposition:v:0 attached_pic dest

2. split_artist_tag(path)
   Reads ARTIST / ALBUMARTIST, splits on common separators (feat., &, /,
   ;, ,) and rewrites as native multi-value tags. For MP3 skips files
   that already hold multiple values in TPE1/TPE2. For album_artist uses
   a solo-album heuristic: if any split part appears in the artist tag
   keep only the first element.

Public API:
    sanitize_m4a_streams(path) -> bool
    split_artist_tag(path, dry_run=False) -> bool
    process_file(path, dry_run=False) -> bool
    process_directory(root, dry_run=False) -> dict

CLI:
    python3 fix_artists.py                        # dry-run ./
    python3 fix_artists.py /path/to/music         # dry-run
    python3 fix_artists.py /path/to/music --write # apply
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

SUPPORTED_EXT: tuple[str, ...] = ("mp3", "flac", "ogg", "opus", "m4a", "aac")

SEPARATORS: tuple[str, ...] = (
    " feat. ",
    " feat ",
    " ft. ",
    " ft ",
    " & ",
    " / ",
    "/",
    "; ",
    ";",
    ", ",
    ",",
)


# ── ffprobe helpers ──────────────────────────────────────────────────────────


def _ffprobe_streams(path: str) -> list[dict]:
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-print_format", "json",
                "-show_streams", path,
            ],
            capture_output=True, text=True,
        )
    except FileNotFoundError:
        logger.warning("ffprobe not found — cannot inspect %s", path)
        return []
    if result.returncode != 0:
        return []
    try:
        return json.loads(result.stdout).get("streams", [])
    except json.JSONDecodeError:
        return []


def _ffprobe_format_tags(path: str) -> dict[str, str]:
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-print_format", "json",
                "-show_format", path,
            ],
            capture_output=True, text=True,
        )
    except FileNotFoundError:
        return {}
    if result.returncode != 0:
        return {}
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}
    return data.get("format", {}).get("tags", {}) or {}


# ── m4a stream sanitation ────────────────────────────────────────────────────


def _is_broken_video_stream(stream: dict) -> bool:
    """A cover-art stream should have r_frame_rate=0/0 and no real duration.
    If the m4a carries a long video stream (seen in some SC exports) or the
    stream isn't marked as attached_pic, the file needs a rewrite."""
    rfr = stream.get("r_frame_rate") or "0/0"
    try:
        dur = float(stream.get("duration") or 0)
    except (TypeError, ValueError):
        dur = 0.0
    if not stream.get("disposition", {}).get("attached_pic"):
        return True
    if rfr not in ("0/0", "0/1") and dur > 1.0:
        return True
    return False


def sanitize_m4a_streams(path: str) -> bool:
    """Return True if the file was rewritten."""
    if not path.lower().endswith(".m4a"):
        return False

    streams = _ffprobe_streams(path)
    if not streams:
        return False

    audio = [s for s in streams if s.get("codec_type") == "audio"]
    video = [s for s in streams if s.get("codec_type") == "video"]

    needs_fix = len(audio) > 1 or any(_is_broken_video_stream(v) for v in video)
    if not needs_fix:
        return False

    name = os.path.basename(path)
    logger.info(
        "sanitize_m4a: rewriting %s (audio=%d, video=%d)",
        name, len(audio), len(video),
    )

    map_args = ["-map", "0:a:0"]
    disp_args: list[str] = []
    if video:
        map_args += ["-map", "0:v:0"]
        disp_args = ["-disposition:v:0", "attached_pic"]

    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".m4a", dir=os.path.dirname(path))
    os.close(tmp_fd)
    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", path, *map_args, "-c", "copy", *disp_args, tmp_path],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            logger.warning(
                "sanitize_m4a: ffmpeg failed for %s, keeping original.\n%s",
                name, result.stderr[-400:],
            )
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            return False
        os.replace(tmp_path, path)
        logger.info("sanitize_m4a: OK — %s", name)
        return True
    except Exception as exc:
        logger.warning("sanitize_m4a: error for %s: %s", name, exc)
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        return False


# ── artist split ─────────────────────────────────────────────────────────────


def split_artist(raw: str) -> list[str]:
    parts = [raw]
    for sep in SEPARATORS:
        new_parts: list[str] = []
        for p in parts:
            new_parts.extend(p.split(sep))
        parts = new_parts
    return [p.strip() for p in parts if p.strip()]


def _needs_split(raw: str) -> bool:
    return any(sep in raw for sep in SEPARATORS)


def _read_tag_pair(path: str) -> tuple[str, str]:
    tags = _ffprobe_format_tags(path)
    artist = ""
    album_artist = ""
    for k, v in tags.items():
        kl = k.lower()
        if kl == "artist":
            artist = str(v)
        elif kl in ("album_artist", "albumartist"):
            album_artist = str(v)
    return artist, album_artist


def _mp3_already_multi(path: str, frame: str) -> bool:
    try:
        from mutagen.mp3 import MP3
    except ImportError:
        return False
    try:
        f = MP3(path)
    except Exception:
        return False
    if not f.tags:
        return False
    tag = f.tags.get(frame)
    return bool(tag and len(tag.text) > 1)


def _write_field(path: str, field: str, artists: list[str]) -> None:
    ext = Path(path).suffix.lower()

    if ext == ".mp3":
        from mutagen.mp3 import MP3
        from mutagen.id3 import TPE1, TPE2

        f = MP3(path)
        if f.tags is None:
            f.add_tags()
        if field == "artist":
            f.tags["TPE1"] = TPE1(encoding=1, text=artists)
            for key in [k for k in f.tags.keys() if k.upper().startswith("TXXX:ARTISTS")]:
                del f.tags[key]
        else:
            f.tags["TPE2"] = TPE2(encoding=1, text=artists)
        f.save(v2_version=4)

    elif ext == ".flac":
        from mutagen.flac import FLAC

        tags = FLAC(path)
        if field == "artist":
            tags["artist"] = artists
            for key in list(tags.keys()):
                if key.lower() == "artists":
                    del tags[key]
        else:
            tags["albumartist"] = artists
        tags.save()

    elif ext in (".ogg", ".opus"):
        if ext == ".opus":
            from mutagen.oggopus import OggOpus as cls
        else:
            from mutagen.oggvorbis import OggVorbis as cls

        tags = cls(path)
        if field == "artist":
            tags["artist"] = artists
            for key in list(tags.keys()):
                if key.lower() == "artists":
                    del tags[key]
        else:
            tags["albumartist"] = artists
        tags.save()

    elif ext in (".m4a", ".aac"):
        from mutagen.mp4 import MP4

        tags = MP4(path)
        if field == "artist":
            tags["\xa9ART"] = artists
            for key in list(tags.keys()):
                if key.lower() in ("artists", "----:com.apple.itunes:artists"):
                    del tags[key]
        else:
            tags["aART"] = artists
        tags.save()

    else:
        raise ValueError(f"Unsupported format: {ext}")


def split_artist_tag(path: str, dry_run: bool = False) -> bool:
    """Split multi-value artist / album_artist tags in-place.
    Returns True if anything changed (or would change in dry-run)."""
    ext = Path(path).suffix.lower().lstrip(".")
    if ext not in SUPPORTED_EXT:
        return False

    raw_artist, raw_album_artist = _read_tag_pair(path)
    changed = False
    header_printed = False

    def _header() -> None:
        nonlocal header_printed
        if not header_printed:
            logger.info("📄 %s", path)
            header_printed = True

    # artist
    if raw_artist and _needs_split(raw_artist):
        skip_mp3_multi = ext == "mp3" and _mp3_already_multi(path, "TPE1")
        if not skip_mp3_multi:
            artists = split_artist(raw_artist)
            if len(artists) > 1:
                _header()
                logger.info("  → artist was : %s", raw_artist)
                logger.info("  → artist will: %s", " | ".join(artists))
                if not dry_run:
                    try:
                        _write_field(path, "artist", artists)
                        logger.info("  ✅ artist written")
                        changed = True
                    except Exception as exc:
                        logger.warning("  ⚠ artist write failed: %s", exc)
                else:
                    changed = True

    # album_artist (solo-album heuristic)
    if raw_album_artist and _needs_split(raw_album_artist):
        aa_parts = split_artist(raw_album_artist)
        if len(aa_parts) > 1:
            is_solo = any(p and p in raw_artist for p in aa_parts)
            if is_solo:
                _header()
                logger.info("  → album_artist was : %s", raw_album_artist)
                logger.info(
                    "  → album_artist will: %s (solo album, others removed)",
                    aa_parts[0],
                )
                if not dry_run:
                    try:
                        _write_field(path, "album_artist", [aa_parts[0]])
                        logger.info("  ✅ album_artist written")
                        changed = True
                    except Exception as exc:
                        logger.warning("  ⚠ album_artist write failed: %s", exc)
                else:
                    changed = True
            else:
                skip_mp3_multi = ext == "mp3" and _mp3_already_multi(path, "TPE2")
                if not skip_mp3_multi:
                    _header()
                    logger.info("  → album_artist was : %s", raw_album_artist)
                    logger.info(
                        "  → album_artist will: %s", " | ".join(aa_parts),
                    )
                    if not dry_run:
                        try:
                            _write_field(path, "album_artist", aa_parts)
                            logger.info("  ✅ album_artist written")
                            changed = True
                        except Exception as exc:
                            logger.warning(
                                "  ⚠ album_artist write failed: %s", exc,
                            )
                    else:
                        changed = True

    return changed


# ── public: process a file / directory ───────────────────────────────────────


def process_file(path: str, dry_run: bool = False) -> bool:
    """Sanitize m4a streams + split multi-value artist tags.
    Returns True if anything changed."""
    ext = Path(path).suffix.lower().lstrip(".")
    if ext not in SUPPORTED_EXT:
        return False

    changed = False
    if ext == "m4a" and not dry_run:
        if sanitize_m4a_streams(path):
            changed = True
    if split_artist_tag(path, dry_run=dry_run):
        changed = True
    return changed


def process_directory(root: str, dry_run: bool = False) -> dict[str, int]:
    scanned = changed = skipped = 0
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            path = os.path.join(dirpath, name)
            ext = Path(path).suffix.lower().lstrip(".")
            if ext not in SUPPORTED_EXT:
                continue
            scanned += 1
            if process_file(path, dry_run=dry_run):
                changed += 1
            else:
                skipped += 1
    return {"scanned": scanned, "changed": changed, "skipped": skipped}


# ── CLI ──────────────────────────────────────────────────────────────────────


def _main() -> int:
    import argparse
    import sys

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    p = argparse.ArgumentParser(description="Fix multi-value artist tags.")
    p.add_argument("path", nargs="?", default=".", help="file or directory")
    p.add_argument("--write", action="store_true", help="apply changes")
    args = p.parse_args()

    if not os.path.exists(args.path):
        print(f"Error: {args.path} not found", file=sys.stderr)
        return 1

    dry = not args.write
    target = os.path.abspath(args.path)
    if dry:
        print("🔍 DRY RUN — pass --write to apply changes")
    print(f"📂 Target: {target}\n")

    if os.path.isfile(args.path):
        process_file(args.path, dry_run=dry)
        return 0

    stats = process_directory(args.path, dry_run=dry)
    print()
    print("━" * 33)
    print(f"Files scanned : {stats['scanned']}")
    label = "Would change" if dry else "Changed"
    print(f"{label:<14}: {stats['changed']}")
    print(f"Skipped       : {stats['skipped']}")
    if dry:
        print("\nRun with --write to apply changes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
