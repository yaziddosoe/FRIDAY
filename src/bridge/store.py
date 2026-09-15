import os
import sqlite3
from datetime import datetime
from pathlib import Path

_DEFAULT_DB = Path(os.path.expanduser("~/.friday/bridge.db"))
_TS = "%Y-%m-%dT%H:%M:%S"

_CREATE_NOTE = (
    "CREATE TABLE IF NOT EXISTS notes ("
    " id INTEGER PRIMARY KEY AUTOINCREMENT,"
    " content TEXT NOT NULL,"
    " created_at TEXT NOT NULL"
    ")"
)
_CREATE_REMINDER = (
    "CREATE TABLE IF NOT EXISTS reminders ("
    " id INTEGER PRIMARY KEY AUTOINCREMENT,"
    " label TEXT NOT NULL,"
    " at TEXT NOT NULL,"
    " fired INTEGER NOT NULL DEFAULT 0,"
    " created_at TEXT NOT NULL"
    ")"
)


def now_ts() -> str:
    return datetime.now().replace(microsecond=0).strftime(_TS)


def normalize_at(value: str) -> str:
    """Parse a user-supplied ISO timestamp into local-naive ``%Y-%m-%dT%H:%M:%S``."""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(
            f"'{value}' is not a valid ISO timestamp; use a format like 2026-09-15T20:00:00"
        ) from exc
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone().replace(tzinfo=None)
    return parsed.replace(microsecond=0).strftime(_TS)


class BridgeStore:
    """SQLite storage for bridge notes and reminders at ``~/.friday/bridge.db``."""

    def __init__(self, db_path: str | os.PathLike[str] | None = None) -> None:
        if db_path is not None:
            self.db_path = Path(str(db_path))
        else:
            self.db_path = Path(os.environ.get("FRIDAY_BRIDGE_DB", _DEFAULT_DB))

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.execute(_CREATE_NOTE)
        conn.execute(_CREATE_REMINDER)
        return conn

    def list_notes(self) -> list[dict[str, object]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT id, content, created_at FROM notes ORDER BY id DESC"
            ).fetchall()
        finally:
            conn.close()
        return [{"id": row[0], "content": row[1], "created_at": row[2]} for row in rows]

    def add_note(self, content: str) -> int:
        conn = self._connect()
        try:
            cur = conn.execute(
                "INSERT INTO notes (content, created_at) VALUES (?, ?)",
                (content, now_ts()),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()

    def delete_note(self, note_id: int) -> int:
        conn = self._connect()
        try:
            cur = conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()

    def list_reminders(self) -> list[dict[str, object]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT id, label, at, fired, created_at FROM reminders ORDER BY at ASC"
            ).fetchall()
        finally:
            conn.close()
        return [
            {
                "id": row[0],
                "label": row[1],
                "at": row[2],
                "fired": row[3],
                "created_at": row[4],
            }
            for row in rows
        ]

    def add_reminder(self, label: str, at: str) -> int:
        conn = self._connect()
        try:
            cur = conn.execute(
                "INSERT INTO reminders (label, at, created_at) VALUES (?, ?, ?)",
                (label, normalize_at(at), now_ts()),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()

    def delete_reminder(self, reminder_id: int) -> int:
        conn = self._connect()
        try:
            cur = conn.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()

    def due_reminders(self, now: str) -> list[dict[str, object]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT id, label, at, fired, created_at FROM reminders "
                "WHERE fired = 0 AND at <= ? ORDER BY at ASC",
                (now,),
            ).fetchall()
        finally:
            conn.close()
        return [
            {
                "id": row[0],
                "label": row[1],
                "at": row[2],
                "fired": row[3],
                "created_at": row[4],
            }
            for row in rows
        ]

    def mark_reminder_fired(self, reminder_id: int) -> None:
        conn = self._connect()
        try:
            conn.execute("UPDATE reminders SET fired = 1 WHERE id = ?", (reminder_id,))
            conn.commit()
        finally:
            conn.close()
