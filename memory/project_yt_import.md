---
name: YouTube playlist import feature
description: How the YouTube playlist import feature works end-to-end
type: project
---

**Implemented:** YouTube playlist scan + selective download + Navidrome import.

Backend:
- `backend/youtube/playlist.py` — fetch playlist via `yt-dlp --dump-single-json --flat-playlist`
- `backend/youtube/matcher.py` — fuzzy-match tracks against Navidrome Subsonic search3 API
- `backend/youtube/downloader.py` — download MP3, retag (preserve thumbnail), run fix-artists.sh
- `backend/api/youtube.py` — `POST /api/yt-scan` (sync) + `POST /api/yt-import` (queues job)
- `backend/worker/main.py` — `yt_import_task` added; downloads → retag → fix-artists.sh → SFTP → scan

Frontend:
- `frontend/src/PlaylistImport.jsx` — URL input, track list with match status, inline edit for unmatched
- `frontend/src/ModeSelector.jsx` — added "youtube" mode button
- `frontend/src/App.jsx` — added "yt-input" state + `handleYtImport`

Each YouTube track is stored as a single: `<artist>/<title> (Single)/<title>.mp3`.
fix-artists.sh runs after retag to split "A & B" → multi-value artist tags.

**Why:** User wanted to migrate YouTube Music playlists into the Navidrome library.
**How to apply:** Match threshold is 0.55 in matcher.py (tunable); zsh must be in container (added to Dockerfile).
