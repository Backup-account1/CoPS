"""Tiny SQLite persistence: settings + event log. Stdlib only."""

import json
import sqlite3
import threading
import time
from pathlib import Path

DB_PATH = Path(__file__).parent / "panel.db"
_lock = threading.Lock()


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH, timeout=5)
    c.row_factory = sqlite3.Row
    return c


def init():
    with _lock, _conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings(
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events(
                id     INTEGER PRIMARY KEY AUTOINCREMENT,
                ts     REAL NOT NULL,
                kind   TEXT NOT NULL,
                detail TEXT
            );
            CREATE TABLE IF NOT EXISTS curves(
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                name    TEXT NOT NULL,
                content TEXT NOT NULL,
                ts      REAL NOT NULL
            );
            """
        )


def get_settings(defaults: dict) -> dict:
    with _lock, _conn() as c:
        rows = c.execute("SELECT key, value FROM settings").fetchall()
    stored = {r["key"]: json.loads(r["value"]) for r in rows}
    return {**defaults, **stored}


def save_settings(s: dict):
    with _lock, _conn() as c:
        for k, v in s.items():
            c.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (k, json.dumps(v)),
            )


def add_event(kind: str, detail: str = ""):
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO events(ts, kind, detail) VALUES(?, ?, ?)",
            (time.time(), kind, detail),
        )


def list_events(limit: int = 30) -> list:
    with _lock, _conn() as c:
        rows = c.execute(
            "SELECT ts, kind, detail FROM events ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def save_curve(name: str, content: str):
    """Keep only the latest curve."""
    with _lock, _conn() as c:
        c.execute("DELETE FROM curves")
        c.execute(
            "INSERT INTO curves(name, content, ts) VALUES(?, ?, ?)",
            (name, content, time.time()),
        )


def load_curve():
    with _lock, _conn() as c:
        r = c.execute(
            "SELECT name, content FROM curves ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return dict(r) if r else None


def clear_curve():
    with _lock, _conn() as c:
        c.execute("DELETE FROM curves")
