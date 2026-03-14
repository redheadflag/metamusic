#!/usr/bin/env python3
"""
yt_sc_fetch — CLI entry point
------------------------------
Modes:

  YouTube (auto-search on SoundCloud):
      python3 -m yt_sc_fetch <youtube_url> [<youtube_url> ...]

  SoundCloud direct (fetch SC metadata, download):
      python3 -m yt_sc_fetch --sc <soundcloud_url> [<soundcloud_url> ...]

  SoundCloud with metadata overrides:
      python3 -m yt_sc_fetch --sc <sc_url> \\
          --artist ARTIST --album ALBUM --year YEAR [--track TRACK] \\
          [--album-artist ALBUM_ARTIST]

Dependencies (install once):
    pip install yt-dlp mutagen
"""

import argparse
import os
import sys

from .sc import fetch_sc_entries, process_sc_entry, validate_sc_overrides
from .utils import log, die
from .youtube import fetch_yt_entries, process_yt_entry


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="yt_sc_fetch",
        description=(
            "Download audio from YouTube (auto-search SC) or SoundCloud directly.\n\n"
            "Examples:\n"
            "  %(prog)s <yt_url> [<yt_url> ...]\n"
            "  %(prog)s --sc <sc_url> [<sc_url> ...]\n"
            "  %(prog)s --sc <sc_url> --artist 'Drake' --album 'Scorpion' --year 2018\n"
            "  %(prog)s --sc <sc_url> --artist 'Drake' --album 'Scorpion' "
            '--year 2018 --track "God\'s Plan"'
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "urls",
        nargs="*",
        help="One or more YouTube or SoundCloud URLs.",
    )
    parser.add_argument(
        "--sc",
        action="store_true",
        help="SoundCloud direct mode.",
    )

    og = parser.add_argument_group(
        "metadata overrides (--sc mode only)",
        "Override metadata fetched from SoundCloud.\n"
        "When any override is given, --artist, --album, and --year are required.\n"
        "--track is also required for single tracks.",
    )
    og.add_argument(
        "--artist", metavar="ARTIST", help="Artist name (comma-separated for multiple)"
    )
    og.add_argument(
        "--album-artist",
        metavar="ALBUM_ARTIST",
        dest="album_artist",
        help="Album artist (defaults to first value in --artist)",
    )
    og.add_argument("--album", metavar="ALBUM", help="Album name")
    og.add_argument("--track", metavar="TRACK", help="Track title (single tracks only)")
    og.add_argument("--year", metavar="YEAR", help="Release year")

    args = parser.parse_args()

    if not args.urls:
        parser.print_help()
        sys.exit(1)

    MUSIC_LIBRARY_PATH = "output"
    os.makedirs(MUSIC_LIBRARY_PATH, exist_ok=True)

    overrides = {
        "artist": args.artist,
        "album_artist": args.album_artist,
        "album": args.album,
        "track": args.track,
        "year": args.year,
    }
    has_overrides = any(v is not None for v in overrides.values())

    # ── SoundCloud direct mode ───────────────────────────────────────────────
    if args.sc:
        total_downloaded = 0
        for url_idx, sc_url in enumerate(args.urls, 1):
            if len(args.urls) > 1:
                log(f"\n══ SC source [{url_idx}/{len(args.urls)}]: {sc_url}")

            entries = fetch_sc_entries(sc_url)
            is_playlist = len(entries) > 1

            if has_overrides:
                validate_sc_overrides(overrides, is_playlist)

            for i, raw in enumerate(entries, 1):
                if is_playlist:
                    log(f"\n[{i}/{len(entries)}]")
                track_number = i if is_playlist else None
                process_sc_entry(
                    raw,
                    MUSIC_LIBRARY_PATH,
                    track_number=track_number,
                    overrides=overrides if has_overrides else None,
                )
                total_downloaded += 1

        log(f"\nFinished. {total_downloaded} track(s) downloaded.")
        return

    # Metadata overrides only apply to --sc mode
    if has_overrides:
        die(
            "Metadata override flags (--artist, --album, etc.) are only supported with --sc."
        )

    # ── YouTube mode ─────────────────────────────────────────────────────────
    skipped_tracks: list[str] = []
    total_entries = 0

    for url_idx, yt_url in enumerate(args.urls, 1):
        if len(args.urls) > 1:
            log(f"\n══ YouTube source [{url_idx}/{len(args.urls)}]: {yt_url}")
        entries = fetch_yt_entries(yt_url)
        total_entries += len(entries)
        is_playlist = len(entries) > 1
        for i, raw in enumerate(entries, 1):
            log(f"\n[{i}/{len(entries)}]")
            track_number = i if is_playlist else None
            skipped = process_yt_entry(
                raw, MUSIC_LIBRARY_PATH=MUSIC_LIBRARY_PATH, track_number=track_number
            )
            if skipped:
                skipped_tracks.append(f"  {len(skipped_tracks) + 1}. {skipped}")

    ok = total_entries - len(skipped_tracks)
    log(f"\nFinished. {ok} downloaded, {len(skipped_tracks)} skipped.")
    if skipped_tracks:
        print("\nSkipped tracks:")
        print("\n".join(skipped_tracks))


if __name__ == "__main__":
    main()
