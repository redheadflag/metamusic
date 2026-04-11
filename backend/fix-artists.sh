#!/usr/bin/env zsh
# fix_artists.sh
# Recursively walks a directory, reads the ARTIST and ALBUMARTIST tags of each
# audio file, splits them on common separators, and rewrites as native
# multi-value tags. Also removes TXXX:ARTISTS / ARTISTS tags if present.
#
# Requirements:
#   ffprobe  →  apt install ffmpeg
#   mutagen  →  pip install mutagen  /  apt install python3-mutagen
#
# Usage:
#   ./fix_artists.sh                        # dry-run on current directory
#   ./fix_artists.sh /path/to/music         # dry-run on given path
#   ./fix_artists.sh /path/to/music --write # write to given path
#   ./fix_artists.sh --write /path/to/music # same, order doesn't matter

# ── args ──────────────────────────────────────────────────────────────────────
DRY_RUN=true
TARGET_DIR="."

for arg in "$@"; do
  [[ $arg == "--write" ]] && DRY_RUN=false
  [[ $arg != --* ]]       && TARGET_DIR="$arg"
done

if [[ ! -d "$TARGET_DIR" ]]; then
  print -- "Error: '$TARGET_DIR' is not a directory." >&2
  exit 1
fi

TARGET_DIR="${TARGET_DIR:A}"

# ── config ────────────────────────────────────────────────────────────────────
SUPPORTED_EXT=(mp3 flac ogg opus m4a aac)

SEPARATORS=(
  ' feat. '
  ' feat '
  ' ft. '
  ' ft '
  ' & '
  ' / '
  '/'
  '; '
  ';'
  ', '
  ','
)

# ── Python helper ─────────────────────────────────────────────────────────────
PYHELPER=$(mktemp /tmp/fix_artists_XXXXXX.py)
trap "rm -f $PYHELPER" EXIT

cat > "$PYHELPER" << 'PYEOF'
import sys

mode = sys.argv[1]

# ── get: read artist and album_artist tags via ffprobe JSON on stdin ──────────
if mode == "get":
    import json
    data = json.load(sys.stdin)
    tags = data.get("format", {}).get("tags", {})
    artist = ""
    album_artist = ""
    for k, v in tags.items():
        kl = k.lower()
        if kl == "artist":
            artist = v
        elif kl in ("album_artist", "albumartist"):
            album_artist = v
    # Output as two lines: artist\nalbum_artist
    print(artist)
    print(album_artist)

# ── get_multi: check if TPE1/TPE2 already hold multiple hidden values ─────────
elif mode == "get_multi":
    from mutagen.mp3 import MP3
    file = sys.argv[2]
    frame = sys.argv[3]  # "TPE1" or "TPE2"
    f = MP3(file)
    tag = f.tags.get(frame)
    if tag and len(tag.text) > 1:
        for a in tag.text:
            print(a)

# ── split ─────────────────────────────────────────────────────────────────────
elif mode == "split":
    raw = sys.argv[2]
    separators = sys.argv[3:]
    parts = [raw]
    for sep in separators:
        new_parts = []
        for p in parts:
            new_parts.extend(p.split(sep))
        parts = new_parts
    for p in parts:
        p = p.strip()
        if p:
            print(p)

# ── write ─────────────────────────────────────────────────────────────────────
elif mode == "write":
    # argv: write <file> <field> <artist1> <artist2> ...
    # field: "artist" or "album_artist"
    from pathlib import Path
    file = sys.argv[2]
    field = sys.argv[3]   # "artist" or "album_artist"
    artists = sys.argv[4:]
    ext = Path(file).suffix.lower()

    if not ext:
        print(f"Could not determine extension for: {file}", file=sys.stderr)
        sys.exit(1)

    if ext == ".mp3":
        from mutagen.mp3 import MP3
        from mutagen.id3 import TPE1, TPE2
        f = MP3(file)
        if field == "artist":
            f.tags["TPE1"] = TPE1(encoding=1, text=artists)
            keys_to_delete = [k for k in f.tags.keys() if k.upper().startswith("TXXX:ARTISTS")]
            for key in keys_to_delete:
                del f.tags[key]
        else:
            f.tags["TPE2"] = TPE2(encoding=1, text=artists)
        f.save(v2_version=4)

    elif ext == ".flac":
        from mutagen.flac import FLAC
        tags = FLAC(file)
        if field == "artist":
            tags["artist"] = artists
            for key in list(tags.keys()):
                if key.lower() == "artists":
                    del tags[key]
        else:
            tags["albumartist"] = artists
        tags.save()

    elif ext in (".ogg", ".opus"):
        from mutagen.oggvorbis import OggVorbis
        from mutagen.oggopus import OggOpus
        cls = OggOpus if ext == ".opus" else OggVorbis
        tags = cls(file)
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
        tags = MP4(file)
        if field == "artist":
            tags["\xa9ART"] = artists
            for key in list(tags.keys()):
                if key.lower() in ("artists", "----:com.apple.itunes:artists"):
                    del tags[key]
        else:
            tags["aART"] = artists
        tags.save()

    else:
        print(f"Unsupported format: {ext}", file=sys.stderr)
        sys.exit(1)

PYEOF

# ── counters ──────────────────────────────────────────────────────────────────
count_files=0
count_changed=0
count_skipped=0

# ── functions ─────────────────────────────────────────────────────────────────
log()  { print -- "$@" }
info() { print -- "  → $@" }
warn() { print -- "  ⚠ $@" >&2 }

get_tags() {
  ffprobe -v quiet -print_format json -show_format "$1" 2>/dev/null \
    | python3 "$PYHELPER" get
}

get_multi_mp3() {
  python3 "$PYHELPER" get_multi "$1" "$2"
}

split_artist() {
  python3 "$PYHELPER" split "$1" "${SEPARATORS[@]}"
}

write_field() {
  python3 "$PYHELPER" write "$@" 2>&1
}

# Process one tag field (artist or album_artist) for a file.
# Returns 0 if a change was made or queued, 1 if skipped.
process_field() {
  local file="$1" field="$2" raw="$3" mp3_frame="$4"
  local -a artists

  [[ -z "$raw" ]] && return 1

  # For MP3: skip if already properly multi-valued
  if [[ "${file:e:l}" == "mp3" ]]; then
    local -a multi=("${(@f)$(get_multi_mp3 "$file" "$mp3_frame")}")
    if [[ ${#multi[@]} -gt 1 ]]; then
      return 1
    fi
  fi

  local sep needs_split=false
  for sep in "${SEPARATORS[@]}"; do
    [[ "$raw" == *"${sep}"* ]] && needs_split=true && break
  done
  $needs_split || return 1

  artists=("${(@f)$(split_artist "$raw")}")
  [[ ${#artists[@]} -le 1 ]] && return 1

  info "${field} was : $raw"
  info "${field} will: ${(j: | :)artists}"

  if ! $DRY_RUN; then
    local err
    err=$(write_field "$file" "$field" "${artists[@]}")
    if [[ $? -eq 0 ]]; then
      info "✅ ${field} written"
    else
      warn "failed (${field}): $err"
      return 1
    fi
  fi
  return 0
}

process_file() {
  local file="$1"
  local ext="${file:e:l}"

  local e is_supported=false
  for e in "${SUPPORTED_EXT[@]}"; do
    [[ $ext == $e ]] && is_supported=true && break
  done
  $is_supported || return

  (( count_files++ ))

  local raw_artist raw_album_artist
  local tag_output
  tag_output=$(get_tags "$file")
  raw_artist="${tag_output%%$'\n'*}"
  raw_album_artist="${tag_output#*$'\n'}"

  local changed=false

  local header_printed=false
  print_header() {
    if ! $header_printed; then
      log "📄 $file"
      header_printed=true
    fi
  }

  # Check artist
  if [[ -n "$raw_artist" ]]; then
    local sep needs_split=false
    for sep in "${SEPARATORS[@]}"; do
      [[ "$raw_artist" == *"${sep}"* ]] && needs_split=true && break
    done
    if $needs_split; then
      print_header
      process_field "$file" "artist" "$raw_artist" "TPE1" && changed=true
    fi
  fi

  # Check album_artist
  if [[ -n "$raw_album_artist" ]]; then
    local sep needs_split=false
    for sep in "${SEPARATORS[@]}"; do
      [[ "$raw_album_artist" == *"${sep}"* ]] && needs_split=true && break
    done
    if $needs_split; then
      # Split album_artist into candidates
      local -a aa_artists=("${(@f)$(split_artist "$raw_album_artist")}")
      if [[ ${#aa_artists[@]} -gt 1 ]]; then
        # Check if any split value appears in the artist tag — solo album logic
        local is_solo=false
        local aa
        for aa in "${aa_artists[@]}"; do
          [[ "$raw_artist" == *"$aa"* ]] && is_solo=true && break
        done
        print_header
        if $is_solo; then
          # Solo album — keep only the first album artist
          info "album_artist was : $raw_album_artist"
          info "album_artist will: ${aa_artists[1]} (solo album, others removed)"
          if ! $DRY_RUN; then
            local err
            err=$(write_field "$file" "album_artist" "${aa_artists[1]}")
            if [[ $? -eq 0 ]]; then
              info "✅ album_artist written"
              changed=true
            else
              warn "failed (album_artist): $err"
            fi
          else
            changed=true
          fi
        else
          # Various artists — split normally
          process_field "$file" "album_artist" "$raw_album_artist" "TPE2" && changed=true
        fi
      fi
    fi
  fi

  if $changed; then
    (( count_changed++ ))
  else
    (( count_skipped++ ))
  fi
}

# ── main ──────────────────────────────────────────────────────────────────────
$DRY_RUN && log "🔍 DRY RUN — no files will be modified (pass --write to apply changes)"
log "📂 Target: $TARGET_DIR\n"

while IFS= read -r -d '' file; do
  process_file "$file"
done < <(find "$TARGET_DIR" -type f -print0)

log ""
log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
log "Files scanned : $count_files"
if $DRY_RUN; then
  log "Would change  : $count_changed"
else
  log "Changed       : $count_changed"
fi
log "Skipped       : $count_skipped"
$DRY_RUN && log "\nRun with --write to apply changes."
