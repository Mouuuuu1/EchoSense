"""
Location + event log.
Primary: SQLite (always local).
Secondary: Firebase Realtime DB REST API (optional, set FIREBASE_URL in config).
"""

import sqlite3
import time
import threading
import requests
from pathlib import Path
from utils.logger import get_logger
import config

log = get_logger(__name__)

DB_PATH = Path(__file__).parent.parent / "echosense.db"


class Database:
    def __init__(self):
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS locations (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts        REAL    NOT NULL,
                    lat       REAL    NOT NULL,
                    lon       REAL    NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts        REAL    NOT NULL,
                    type      TEXT    NOT NULL,
                    detail    TEXT
                );
            """)
        log.info("Database ready at %s", DB_PATH)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(DB_PATH))

    # ── writes ────────────────────────────────────────────────────────────────

    def log_location(self, lat: float, lon: float):
        ts = time.time()
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO locations (ts, lat, lon) VALUES (?, ?, ?)",
                    (ts, lat, lon),
                )
        self._firebase_push("locations", {"ts": ts, "lat": lat, "lon": lon})

    def log_event(self, event_type: str, detail: str = ""):
        ts = time.time()
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO events (ts, type, detail) VALUES (?, ?, ?)",
                    (ts, event_type, detail),
                )
        self._firebase_push("events", {"ts": ts, "type": event_type, "detail": detail})

    # ── reads ─────────────────────────────────────────────────────────────────

    def recent_locations(self, limit: int = 100) -> list[dict]:
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT ts, lat, lon FROM locations ORDER BY ts DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [{"ts": r[0], "lat": r[1], "lon": r[2]} for r in rows]

    def recent_events(self, limit: int = 50) -> list[dict]:
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT ts, type, detail FROM events ORDER BY ts DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [{"ts": r[0], "type": r[1], "detail": r[2]} for r in rows]

    # ── Firebase ──────────────────────────────────────────────────────────────

    def _firebase_push(self, collection: str, data: dict):
        if not config.FIREBASE_URL:
            return
        url = f"{config.FIREBASE_URL.rstrip('/')}/{collection}.json"
        params = {}
        if config.FIREBASE_SECRET:
            params["auth"] = config.FIREBASE_SECRET
        try:
            requests.post(url, json=data, params=params, timeout=5)
        except Exception as e:
            log.debug("Firebase push failed: %s", e)

    def firebase_update_status(self, status: dict):
        """Update the live /status node in Firebase."""
        if not config.FIREBASE_URL:
            return
        url = f"{config.FIREBASE_URL.rstrip('/')}/status.json"
        params = {"auth": config.FIREBASE_SECRET} if config.FIREBASE_SECRET else {}
        try:
            requests.put(url, json=status, params=params, timeout=5)
        except Exception as e:
            log.debug("Firebase status update failed: %s", e)
