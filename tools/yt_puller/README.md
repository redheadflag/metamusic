# yt_puller

Local worker that claims pending YouTube download jobs from the VPS queue,
downloads each track with yt-dlp, tags it with mutagen, uploads via SFTP,
and reports success/failure back to the API.

## Setup

```bash
cd tools/yt_puller
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then edit .env
```

## .env

```
API_BASE=https://yourserver.com/api
PULLER_TOKEN=your_shared_secret        # matches YT_PULLER_TOKEN in backend/.env
SFTP_HOST=yourserver.com
SFTP_PORT=22
SFTP_USER=youruser
SFTP_KEY_FILE=/home/you/.ssh/id_ed25519
SFTP_BASE=/home/youruser/music
YOUTUBE_COOKIES_FILE=/path/to/cookies.txt   # optional
CLAIM_LIMIT=3          # jobs per poll cycle (default 3)
POLL_INTERVAL=30       # seconds between idle polls (default 30)
```

## Run

```bash
python -m yt_puller.main
```

Or with make:

```bash
make run
```

The puller runs indefinitely, polling every `POLL_INTERVAL` seconds when idle.
Interrupt with Ctrl-C.
