import os
import sqlite3

DB_PATH = os.environ.get("DB_PATH", "metamusic.db")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id INTEGER PRIMARY KEY,
                username    TEXT NOT NULL,
                password    TEXT NOT NULL
            )
        """)
        conn.commit()


def save_user(telegram_id: int, username: str, password: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO users (telegram_id, username, password) VALUES (?, ?, ?)",
            (telegram_id, username, password),
        )
        conn.commit()


def get_user(telegram_id: int) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT username, password FROM users WHERE telegram_id = ?",
            (telegram_id,),
        ).fetchone()
        return dict(row) if row else None


def delete_user(telegram_id: int) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM users WHERE telegram_id = ?", (telegram_id,))
        conn.commit()
