import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS individuals (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    sex TEXT,
    birth_year INTEGER,
    notes TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS samples (
    id INTEGER PRIMARY KEY,
    individual_id INTEGER NOT NULL REFERENCES individuals(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,              -- face | body
    crop_path TEXT NOT NULL,         -- relativně k data/media
    source TEXT NOT NULL,            -- ze kterého souboru výřez pochází (kvůli férovému vyhodnocení)
    origin TEXT NOT NULL,            -- enroll | confirmed
    model_id TEXT,
    embedding BLOB,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS samples_individual ON samples(individual_id);
CREATE TABLE IF NOT EXISTS identifications (
    id INTEGER PRIMARY KEY,
    media_path TEXT NOT NULL,
    media_type TEXT NOT NULL,        -- image | video
    result_json TEXT NOT NULL,
    confirmed_individual_id INTEGER REFERENCES individuals(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL
);
"""

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(settings.db_path, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA foreign_keys = ON")
        _conn.executescript(SCHEMA)
    return _conn


def reset_connection():
    global _conn
    if _conn is not None:
        _conn.close()
    _conn = None


@contextmanager
def tx():
    with _lock:
        conn = connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def query(sql: str, params=()) -> list[sqlite3.Row]:
    with _lock:
        return connect().execute(sql, params).fetchall()
