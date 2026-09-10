from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

from sassessment.errors import StateError


class Database:
    """Thin, safe wrapper over sqlite3 with WAL, foreign keys and explicit transactions."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._conn: Optional[sqlite3.Connection] = None

    def connect(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.path), isolation_level=None, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA synchronous=NORMAL")
        self._conn = conn
        return conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def execute(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
        return self.connect().execute(sql, params)

    def query(self, sql: str, params: Sequence[Any] = ()) -> List[sqlite3.Row]:
        cursor = self.connect().execute(sql, params)
        rows = cursor.fetchall()
        cursor.close()
        return rows

    def query_one(self, sql: str, params: Sequence[Any] = ()) -> Optional[sqlite3.Row]:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def transaction(self) -> "_Transaction":
        return _Transaction(self)

    def backup_to(self, target_path: Path) -> None:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        source = self.connect()
        target = sqlite3.connect(str(target_path))
        try:
            source.backup(target)
            target.commit()
        finally:
            target.close()

    def table_names(self) -> List[str]:
        rows = self.query("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        return [str(row["name"]) for row in rows]

    def __enter__(self) -> "Database":
        self.connect()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


class _Transaction:
    def __init__(self, db: Database) -> None:
        self._db = db

    def __enter__(self) -> sqlite3.Connection:
        conn = self._db.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as exc:
            raise StateError("could not acquire database transaction", details={"error": str(exc)}) from exc
        return conn

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        conn = self._db.connect()
        if exc_type is None:
            conn.execute("COMMIT")
        else:
            conn.execute("ROLLBACK")
        return False


class Migrator:
    """Applies versioned migrations recorded in the ``schema_migrations`` table."""

    def __init__(self, db: Database, migrations: Sequence[Tuple[int, str, str]]) -> None:
        self.db = db
        self.migrations = list(migrations)

    def current_version(self) -> int:
        conn = self.db.connect()
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
        )
        row = self.db.query_one("SELECT MAX(version) AS version FROM schema_migrations")
        return int(row["version"]) if row and row["version"] is not None else 0

    def apply_all(self) -> List[int]:
        applied: List[int] = []
        self.current_version()
        for version, name, sql in sorted(self.migrations, key=lambda m: m[0]):
            if version <= self.current_version():
                continue
            conn = self.db.connect()
            conn.executescript(sql)
            with self.db.transaction() as txn:
                txn.execute(
                    "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, strftime('%Y-%m-%dT%H:%M:%SZ','now'))",
                    (version, name),
                )
            applied.append(version)
        return applied

    def applied_names(self) -> Iterable[Tuple[int, str]]:
        self.current_version()
        rows = self.db.query("SELECT version, name FROM schema_migrations ORDER BY version")
        return [(int(r["version"]), str(r["name"])) for r in rows]
