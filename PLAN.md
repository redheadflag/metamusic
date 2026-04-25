# Unified Media Importer — Implementation Plan

## Goal

Replace two separate import flows (YouTube via SQLite queue + external worker; SoundCloud via ARQ internal jobs) with a single unified system:

**scan URL → review/edit metadata → queue → external worker downloads both sources**

Both YouTube and SoundCloud support single tracks and playlists. The external worker is renamed and extended to handle both. All downloading goes through the SQLite queue — no more ARQ-based SoundCloud processing.

---

## How Navidrome matching works (current, YouTube only)

`POST /api/yt-scan` calls `youtube/matcher.py find_in_navidrome(title, artist)`:
- Searches Navidrome via Subsonic `search3`, up to 15 results
- Scores each: `title_sim × 0.7 + artist_sim × 0.3` (Jaccard word-set overlap, accent-stripped)
- Match threshold: 0.55
- If matched: track is flagged `in_navidrome=true` with its `navidrome_id`
- At import time: matched tracks are added to Navidrome playlist immediately (no download); only unmatched tracks are queued

In the new system, the same matcher runs for **both** YouTube and SoundCloud tracks — it is source-agnostic.

---

## Phase 1 — Queue Schema Extension

**File: `backend/services/download_queue.py`**

Rename table `yt_downloads` → `media_downloads`. Add columns:

```sql
source        TEXT DEFAULT 'youtube'   -- 'youtube' | 'soundcloud'
source_url    TEXT                     -- full URL (SC permalink / YT video URL)
download_mode TEXT DEFAULT 'playlist'  -- 'album' | 'playlist'
album_cover_b64 TEXT                   -- shared cover for album mode (one per album batch)
track_number  INTEGER                  -- position in album/playlist
```

Migration: `ALTER TABLE yt_downloads RENAME TO media_downloads` + `ALTER TABLE ... ADD COLUMN ...` for each new column.

Update `enqueue()` signature to accept `source`, `source_url`, `download_mode`, `album_cover_b64`, `track_number`. Update `claim()` return payload and `list_all()` output to include new fields.

---

## Phase 2 — New Pydantic Models

**File: `backend/models.py`**

Remove: `YtTrackScan`, `YtPlaylistScan`, `YtTrackImport`, `YtImportRequest`

Add:

```python
class MediaTrackScan(BaseModel):
    """Returned from /api/scan — one track, pre-matched against Navidrome."""
    source_id: str           # video_id for YT; permalink slug or track ID for SC
    source_url: str          # full playable URL
    title: str
    artists: list[str]
    album_artists: list[str]
    album: str
    release_year: str
    duration: int | None
    thumbnail: str | None
    cover_art_b64: str | None
    in_navidrome: bool = False
    navidrome_id: str | None = None
    skip: bool = False

class MediaScanResult(BaseModel):
    """Response from /api/scan."""
    source: str              # 'youtube' | 'soundcloud'
    type: str                # 'single' | 'playlist'
    playlist_name: str
    tracks: list[MediaTrackScan]

class MediaImportRequest(BaseModel):
    """Body for /api/import."""
    source: str
    tracks: list[MediaTrackScan]   # with user-edited metadata + skip flags
    playlist_name: str
    username: str
    download_mode: str       # 'album' | 'playlist'
    # album-mode shared metadata (overrides per-track fields):
    album_cover_b64: str | None = None
    album_artist: str | None = None
    album_title: str | None = None
    release_year: str | None = None
```

---

## Phase 3 — Unified Backend API

**New file: `backend/api/media.py`**

### Endpoints to add

```
POST /api/scan          — detect source from URL, fetch metadata, run Navidrome matching
POST /api/import        — queue all tracks (replaces yt-import + sc-process)
GET  /api/queue         — list queue (replaces /api/yt-queue)
POST /api/queue/claim   — worker claims jobs (replaces /api/yt-queue/claim)
POST /api/queue/{id}/done   — worker reports success
POST /api/queue/{id}/failed — worker reports failure
```

### `/api/scan` logic

```python
# Detect source
if 'youtube.com' or 'youtu.be' in url:
    source = 'youtube'
    # single video: fetch_video(url) → MediaScanResult(type='single', tracks=[...])
    # playlist:     fetch_playlist(url) → MediaScanResult(type='playlist', tracks=[...])
elif 'soundcloud.com' in url:
    source = 'soundcloud'
    # resolve_url(url) handles single tracks and playlists

# Run Navidrome matching for all tracks (both sources)
for track in tracks:
    found, nav_id = find_in_navidrome(track.title, track.artists[0])
    track.in_navidrome = found
    track.navidrome_id = nav_id
```

### `/api/import` logic

Same as current `yt-import`:
1. Tracks where `in_navidrome=True` and not `skip`: add to Navidrome playlist immediately
2. Tracks where `in_navidrome=False` and not `skip`: enqueue in `media_downloads`
3. Create/update Navidrome playlist with matched tracks

In album mode, `album_cover_b64`, `album_artist`, `album_title`, `release_year` override per-track fields when enqueueing.

### Endpoints to remove

| Old endpoint | Replaced by |
|---|---|
| `POST /api/yt-fetch-video` | `/api/scan` |
| `POST /api/yt-scan` | `/api/scan` |
| `POST /api/yt-import` | `/api/import` |
| `POST /api/sc-fetch` | `/api/scan` |
| `POST /api/sc-process` | `/api/import` → queue |
| `GET  /api/yt-queue` | `/api/queue` |
| `POST /api/yt-queue/claim` | `/api/queue/claim` |
| `POST /api/yt-queue/{id}/done` | `/api/queue/{id}/done` |
| `POST /api/yt-queue/{id}/failed` | `/api/queue/{id}/failed` |

**Keep** `POST /api/sc-fetch-artist` — artist URL import is a separate scenario (see below).

**Update `backend/main.py`**: unregister old routers, register `media_router`. Keep ARQ worker registration for file uploads.

**Remove from `backend/api/jobs.py`**: `sc_process_task` and related ARQ helpers. Keep `process_album_task` and `process_bulk_task` for direct file uploads.

**Delete**: `backend/api/youtube.py`, `backend/api/soundcloud.py`

---

## Phase 4 — External Worker Extension

**Rename: `tools/yt_puller/` → `tools/media_puller/`**

**File: `tools/media_puller/main.py`**

### New source dispatch in `process_job()`

```python
source = job.get("source", "youtube")
source_url = job.get("source_url") or f"https://www.youtube.com/watch?v={job['video_id']}"
download_mode = job.get("download_mode", "playlist")

if source == "youtube":
    mp3_path = download_youtube_track(source_url, tmp_dir)
elif source == "soundcloud":
    mp3_path = download_soundcloud_track(source_url, tmp_dir)
```

### New `download_soundcloud_track(sc_url, dest_dir) -> str`

Uses yt-dlp on the SC URL directly:
```python
cmd = [
    _ytdlp_bin(),
    "--extract-audio", "--audio-format", "mp3", "--audio-quality", "0",
    "--embed-metadata", "--embed-thumbnail",
    "--output", output_tmpl,
    "--no-playlist", "--quiet",
    *cookies_args,    # SC_COOKIES_FILE env var
    sc_url,
]
```

Returns path to downloaded `.mp3`.

### Album mode cover handling

```python
if download_mode == "album":
    cover_b64 = job.get("album_cover_b64") or job.get("cover_art_b64")
    if cover_b64:
        cover_bytes = _crop_to_square(base64.b64decode(cover_b64))
        _embed_cover(mp3_path, cover_bytes)
        # Save cover.jpg once per album folder
        album_dir = str(PurePosixPath(remote).parent)
        cover_remote = f"{album_dir}/cover.jpg"
        cover_tmp = os.path.join(tmp_dir, "cover.jpg")
        Path(cover_tmp).write_bytes(cover_bytes)
        _sftp_client.upload(cover_tmp, cover_remote)
else:
    # existing per-track cover logic (cover_art_b64 → thumbnail → crop embedded)
```

### Updated API endpoint calls

`/yt-queue/claim` → `/queue/claim`, `/yt-queue/{id}/done` → `/queue/{id}/done`, etc.

### New env vars

| Var | Purpose |
|---|---|
| `SC_COOKIES_FILE` | Optional SoundCloud cookies file for yt-dlp |

---

## Phase 5 — Frontend Unification

### `PlaylistImport.jsx` → `MediaImport.jsx`

Single component replacing both the YouTube import UI and the SoundCloud fetch/process UI.

**URL input & scan**:
- Single URL field, no source selection needed (backend auto-detects)
- On submit: call `POST /api/scan`
- Response drives the rest of the UI

**Download mode toggle** (shown when `tracks.length > 1`):
- "Playlist" (default): per-track metadata editing (current YouTube UX)
- "Album": shared metadata form

**Album mode UI**:
- One album artist field (applies to all tracks)
- One album title field
- One release year field
- One cover art picker (shown to user as "Album cover — saved as cover.jpg")
- Track list shows only titles + reorder handles (no per-track editing)

**Playlist mode UI** (existing YouTube UX, now also for SoundCloud):
- Per-track row with match status (✓ = in Navidrome, ✕ = will download)
- Edit button → modal with title, artists, album artists, album, release year, cover art upload
- Skip toggle

**Import submit**: calls `POST /api/import` with `download_mode` field + shared album metadata if applicable.

**State changes in `App.jsx`**:
- Merge `youtube` mode and `soundcloud` mode → single `import` mode
- Remove soundcloud-specific state and handlers

### `YtQueuePanel.jsx` → `QueuePanel.jsx`

- Update poll endpoint: `/api/yt-queue` → `/api/queue`
- Add `source` badge per row (YouTube / SoundCloud)
- No other changes needed

### Files to delete/remove

- Remove SC import UI component (whatever renders under `soundcloud` mode in `App.jsx`)
- Update all references from `youtube` mode to `import` mode

---

## Separate Scenario: Artist URL Import (SoundCloud)

This is a distinct flow — keep `POST /api/sc-fetch-artist` for now, but build the frontend to use it.

**Flow**:
1. User enters a SoundCloud artist URL (e.g. `https://soundcloud.com/artistname`)
2. Backend detects it's an artist URL in `/api/scan` (kind = 'user' from SC API)
3. Return a list of albums (each is a `MediaScanResult`)
4. Frontend shows a discography browser: album cards with title, track count, cover art
5. User selects one or more albums to import
6. Each selected album goes through the standard album-mode import (same flow as Phase 5)
7. All tracks from selected albums are queued in a single `/api/import` call

**Backend change**: `/api/scan` handles artist URLs by calling `resolve_artist()` and returning `type: 'artist'` with `albums: list[MediaScanResult]` instead of `tracks`.

**Frontend**: New `ArtistImport` sub-view within `MediaImport.jsx` (or a sibling component), shown when scan result `type == 'artist'`.

---

## Cleanup Summary

### Backend files to delete
- `backend/api/youtube.py`
- `backend/api/soundcloud.py`
- Remove `sc_process_task` from `backend/api/jobs.py`

### Backend files to update
- `backend/models.py` — replace Yt* models with Media* models
- `backend/main.py` — swap router registrations
- `backend/services/download_queue.py` — schema migration + new fields
- `backend/youtube/matcher.py` — no changes needed (already source-agnostic)

### Worker directory
- `tools/yt_puller/` → `tools/media_puller/`

### Frontend files
- `PlaylistImport.jsx` → `MediaImport.jsx`
- `YtQueuePanel.jsx` → `QueuePanel.jsx`
- `App.jsx` — merge import modes

---

## Execution Order

1. Queue schema migration + `download_queue.py` service layer
2. New `models.py` (Media* models replacing Yt* models)
3. `backend/api/media.py` + update `backend/main.py`
4. Worker extension (`tools/media_puller/main.py`)
5. Frontend: `MediaImport.jsx` (scan + album/playlist toggle + import submit)
6. Frontend: `QueuePanel.jsx` update + `App.jsx` mode merge
7. Frontend: Artist discography browser (separate scenario)
8. Delete old files

---

## Open Questions (resolved)

- **SC Navidrome matching**: yes, use same matcher for both sources
- **Artist URL import**: separate scenario, added above
- **File path / SFTP structure**: keep current behavior (`SFTP_BASE/artist/album/track.mp3`)
