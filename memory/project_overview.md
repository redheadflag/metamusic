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
fix-artists.sh: zsh script at project root + copied to `backend/fix-artists.sh` for Docker; splits multi-artist strings into multi-value tags. Requires zsh (added to Dockerfile).

**How to apply:** When suggesting changes, follow the existing ARQ job pattern: endpoint → enqueue_job → worker task → SFTP upload → trigger_scan.
