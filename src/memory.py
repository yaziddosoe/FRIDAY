import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_DEFAULT_DB = Path(os.path.expanduser("~/.friday/memory.db"))


class MemoryStore:
    """A tiny SQLite-backed store for facts FRIDAY remembers about the user.

    Facts persist across sessions and process restarts. The database lives at
    ``~/.friday/memory.db`` by default and can be overridden with the
    ``FRIDAY_MEMORY_DB`` environment variable. A fresh connection is opened per
    operation (except for ``:memory:`` databases, which must share a single
    connection), so the store is safe to use across threads.
    """

    def __init__(self, db_path: str | os.PathLike[str] | None = None) -> None:
        if db_path is not None:
            self.db_path = Path(str(db_path))
        else:
            self.db_path = Path(os.environ.get("FRIDAY_MEMORY_DB", _DEFAULT_DB))
        self._shared: sqlite3.Connection | None = None

    def _is_in_memory(self) -> bool:
        return str(self.db_path) == ":memory:"

    def _connect(self) -> tuple[sqlite3.Connection, bool]:
        shared = self._is_in_memory()
        if shared:
            if self._shared is None:
                self._shared = sqlite3.connect(":memory:")
            conn = self._shared
        else:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS facts ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  content TEXT NOT NULL,"
            "  created_at TEXT NOT NULL"
            ")"
        )
        return conn, shared

    def _close(self, conn: sqlite3.Connection, shared: bool) -> None:
        if not shared:
            conn.close()

    def add_fact(self, content: str) -> int:
        conn, shared = self._connect()
        try:
            cur = conn.execute(
                "INSERT INTO facts (content, created_at) VALUES (?, ?)",
                (content, datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            self._close(conn, shared)

    def get_facts(self) -> list[str]:
        if not self._is_in_memory() and not self.db_path.exists():
            return []
        conn, shared = self._connect()
        try:
            rows = conn.execute("SELECT content FROM facts ORDER BY id ASC").fetchall()
            return [row[0] for row in rows]
        finally:
            self._close(conn, shared)

    def forget_fact(self, keyword: str) -> int:
        conn, shared = self._connect()
        try:
            cur = conn.execute(
                "DELETE FROM facts WHERE lower(content) LIKE ?",
                (f"%{keyword.lower()}%",),
            )
            conn.commit()
            return cur.rowcount
        finally:
            self._close(conn, shared)

    def has_facts(self) -> bool:
        return bool(self.get_facts())
