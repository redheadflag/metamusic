"""
SQLite-backed download queue for media tracks (YouTube + SoundCloud).

Path is read from $DOWNLOAD_QUEUE_DB (default /app/data/queue.db).
"""

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

DB_PATH = os.environ.get("DOWNLOAD_QUEUE_DB", "/app/data/queue.db")

_CREATE = """
CREATE TABLE IF NOT EXISTS media_downloads (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id      TEXT NOT NULL UNIQUE,
    title         TEXT NOT NULL,
    artists       TEXT NOT NULL,
    album_artists TEXT NOT NULL DEFAULT '[]',
    album         TEXT NOT NULL DEFAULT '',
    release_year  TEXT NOT NULL DEFAULT '',
    thumbnail     TEXT,
    cover_art_b64 TEXT,
    duration      INTEGER,
    playlist_id   TEXT,
    playlist_name TEXT,
    source        TEXT NOT NULL DEFAULT 'youtube',
    source_url    TEXT,
    download_mode TEXT NOT NULL DEFAULT 'playlist',
    album_cover_b64 TEXT,
    track_number  INTEGER,
    status        TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','claimed','done','failed')),
    claimed_by    TEXT,
    claimed_at    TEXT,
    done_at       TEXT,
    error         TEXT,
    remote_path   TEXT,
    navidrome_id  TEXT,
    created_at    TEXT NOT NULL
);
"""

@contextmanager
def _conn():
    parent = os.path.dirname(DB_PATH)
    if parent:
        os.makedirs(parent, exist_ok=True)
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("DROP TABLE IF EXISTS yt_downloads")
    con.execute(_CREATE)
    try:
        yield con
        con.commit()
    finally:
        con.close()


def _to_dict(row) -> dict:
    d = dict(row)
    d["artists"] = json.loads(d["artists"])
    try:
        d["album_artists"] = json.loads(d.get("album_artists") or "[]")
    except (json.JSONDecodeError, TypeError):
        d["album_artists"] = []
    return d


def enqueue(
    video_id: str,
    title: str,
    artists: list,
    album_artists: list,
    album: str,
    release_year: str,
    thumbnail: str | None,
    cover_art_b64: str | None,
    duration,
    playlist_id,
    playlist_name,
    source: str = "youtube",
    source_url: str | None = None,
    download_mode: str = "playlist",
    album_cover_b64: str | None = None,
    track_number: int | None = None,
) -> int:
    """Insert a pending entry; on conflict reset to pending. Returns the row id."""
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as con:
        cur = con.execute(
            """
            INSERT INTO media_downloads
                (video_id, title, artists, album_artists, album, release_year, thumbnail,
                 cover_art_b64, duration, playlist_id, playlist_name,
                 source, source_url, download_mode, album_cover_b64, track_number,
                 created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(video_id) DO UPDATE SET
                title=excluded.title,
                artists=excluded.artists,
                album_artists=excluded.album_artists,
                album=excluded.album,
                release_year=excluded.release_year,
                thumbnail=excluded.thumbnail,
                cover_art_b64=excluded.cover_art_b64,
                source=excluded.source,
                source_url=excluded.source_url,
                download_mode=excluded.download_mode,
                album_cover_b64=excluded.album_cover_b64,
                track_number=excluded.track_number,
                status='pending',
                error=NULL,
                claimed_by=NULL,
                claimed_at=NULL,
                done_at=NULL,
                remote_path=NULL
            """,
            (
                video_id,
                title,
                json.dumps(artists, ensure_ascii=False),
                json.dumps(album_artists, ensure_ascii=False),
                album or "",
                release_year or "",
                thumbnail,
                cover_art_b64,
                duration,
                playlist_id,
                playlist_name,
                source,
                source_url,
                download_mode,
                album_cover_b64,
                track_number,
                now,
            ),
        )
        return cur.lastrowid


def claim(limit: int, worker_id: str) -> list[dict]:
    """Mark up to *limit* pending rows as claimed and return them."""
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as con:
        rows = con.execute(
            "SELECT id FROM media_downloads WHERE status='pending' LIMIT ?",
            (limit,),
        ).fetchall()
        ids = [r["id"] for r in rows]
        if not ids:
            return []
        ph = ",".join("?" * len(ids))
        con.execute(
            f"UPDATE media_downloads SET status='claimed', claimed_by=?, claimed_at=?"
            f" WHERE id IN ({ph})",
            [worker_id, now, *ids],
        )
        result = con.execute(
            f"SELECT * FROM media_downloads WHERE id IN ({ph})", ids
        ).fetchall()
    return [_to_dict(r) for r in result]


def mark_done(row_id: int, remote_path: str, navidrome_id) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as con:
        con.execute(
            "UPDATE media_downloads SET status='done', done_at=?, remote_path=?, navidrome_id=?"
            " WHERE id=?",
            (now, remote_path, navidrome_id, row_id),
        )


def mark_failed(row_id: int, error: str) -> None:
    with _conn() as con:
        con.execute(
            "UPDATE media_downloads SET status='failed', error=? WHERE id=?",
            (error, row_id),
        )


def get_by_id(row_id: int) -> dict | None:
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM media_downloads WHERE id=?", (row_id,)
        ).fetchone()
    return _to_dict(row) if row else None


def list_all(status: str | None = None) -> list[dict]:
    with _conn() as con:
        if status:
            rows = con.execute(
                "SELECT * FROM media_downloads WHERE status=? ORDER BY created_at",
                (status,),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM media_downloads ORDER BY created_at"
            ).fetchall()
    return [_to_dict(r) for r in rows]
