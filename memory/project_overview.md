---
name: metamusic project overview
description: Tech stack, architecture, and key file locations for the metamusic project
type: project
---

**Why:** Personal music library manager that uploads/imports to Navidrome via SFTP.

FastAPI backend + ARQ worker + Telegram bot (all from `./backend/`), React 19 frontend (Vite).
Upload pipeline: frontend → `/api/*` → Redis/ARQ → worker downloads/tags → SFTP → Navidrome scan.

Key config: `backend/.env` (SC, SFTP, Navidrome creds), `config/yt-dlp.conf` (SC cookies path).
Cookie files: `SC_COOKIES_FILE` (env) or `/app/config/cookies.txt` (default); `YOUTUBE_COOKIES_FILE` (env).
fix_artists: `backend/fix_artists.py` — Python module (replaces the old zsh fix-artists.sh). Splits multi-artist tags (mutagen) and sanitizes .m4a containers (ffmpeg `-map 0:a:0 -map 0:v:0 -c copy -disposition:v:0 attached_pic`). Public API: `sanitize_m4a_streams(path)`, `split_artist_tag(path)`, `process_file(path)`. Called per-file after embed_tags / retag in SC, files, and YT pipelines.

**How to apply:** When suggesting changes, follow the existing ARQ job pattern: endpoint → enqueue_job → worker task → SFTP upload → trigger_scan.
