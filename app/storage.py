
"""Persistent SQLite storage for Aegis AI telemetry."""

import math
import os
import sqlite3

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


from app.incidents import (
    INCIDENT_SCHEMA,
    update_incidents,
    replay_snapshots,
)


DEFAULT_DB_PATH = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "aegis.db"
)


SCHEMA = """
CREATE TABLE IF NOT EXISTS telemetry_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    captured_at TEXT NOT NULL,
    threshold_ms REAL NOT NULL CHECK (threshold_ms > 0),
    severity TEXT NOT NULL CHECK (
        severity IN (
            'none',
            'unknown',
            'medium',
            'high',
            'critical'
        )
    ),
    source TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS backend_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER NOT NULL,
    backend TEXT NOT NULL,
    healthy INTEGER NOT NULL CHECK (healthy IN (0, 1)),
    ewma_ms REAL CHECK (ewma_ms >= 0),
    FOREIGN KEY (snapshot_id)
        REFERENCES telemetry_snapshots(id)
        ON DELETE CASCADE,
    UNIQUE (snapshot_id, backend)
);

CREATE TABLE IF NOT EXISTS snapshot_findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER NOT NULL,
    backend TEXT NOT NULL,
    issue TEXT NOT NULL,
    evidence TEXT NOT NULL,
    FOREIGN KEY (snapshot_id)
        REFERENCES telemetry_snapshots(id)
        ON DELETE CASCADE,
    UNIQUE (snapshot_id, backend, issue)
);

CREATE INDEX IF NOT EXISTS idx_snapshots_captured_at
    ON telemetry_snapshots(captured_at);

CREATE INDEX IF NOT EXISTS idx_backend_samples_backend
    ON backend_samples(backend, snapshot_id);

CREATE INDEX IF NOT EXISTS idx_findings_backend_issue
    ON snapshot_findings(backend, issue);
"""


def get_db_path() -> Path:
    configured = os.getenv("AEGIS_DB_PATH")

    if configured:
        return Path(configured).expanduser()

    return DEFAULT_DB_PATH


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(
        timespec="microseconds"
    )


@contextmanager
def connect(db_path=None):
    """Open a database connection with transaction handling."""

    path = (
        Path(db_path)
        if db_path is not None
        else get_db_path()
    )

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    connection = sqlite3.connect(
        str(path),
        timeout=5.0,
    )

    connection.row_factory = sqlite3.Row

    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")

        yield connection

        connection.commit()

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


def initialize_db(db_path=None):
    """Create the database schema if it does not exist."""

    with connect(db_path) as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.executescript(SCHEMA + INCIDENT_SCHEMA)
        connection.execute("BEGIN IMMEDIATE")
        replay_snapshots(connection)


def save_snapshot(
    incident: dict,
    db_path=None,
) -> int:
    """Persist a validated incident snapshot atomically."""

    threshold = incident["threshold_ms"]

    if (
        isinstance(threshold, bool)
        or not isinstance(threshold, (int, float))
        or not math.isfinite(threshold)
        or threshold <= 0
    ):
        raise ValueError("Invalid snapshot threshold")

    if not incident["backends"]:
        raise ValueError("Snapshot contains no backends")

    captured_at = utc_now()

    with connect(db_path) as connection:

        cursor = connection.execute(
            """
            INSERT INTO telemetry_snapshots (
                captured_at,
                threshold_ms,
                severity,
                source
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                captured_at,
                threshold,
                incident["severity"],
                incident["source"],
            ),
        )

        snapshot_id = cursor.lastrowid

        for backend in incident["backends"]:

            connection.execute(
                """
                INSERT INTO backend_samples (
                    snapshot_id,
                    backend,
                    healthy,
                    ewma_ms
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    backend["name"],
                    int(backend["healthy"]),
                    backend["ewma_ms"],
                ),
            )

        for finding in incident["findings"]:

            connection.execute(
                """
                INSERT INTO snapshot_findings (
                    snapshot_id,
                    backend,
                    issue,
                    evidence
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    finding["backend"],
                    finding["issue"],
                    finding["evidence"],
                ),
            )

        update_incidents(connection, snapshot_id)

        return snapshot_id


def get_snapshot(
    snapshot_id: int,
    db_path=None,
):
    """Retrieve a complete stored telemetry snapshot."""

    with connect(db_path) as connection:

        snapshot = connection.execute(
            """
            SELECT *
            FROM telemetry_snapshots
            WHERE id = ?
            """,
            (snapshot_id,),
        ).fetchone()

        if snapshot is None:
            return None

        backends = connection.execute(
            """
            SELECT backend, healthy, ewma_ms
            FROM backend_samples
            WHERE snapshot_id = ?
            ORDER BY backend
            """,
            (snapshot_id,),
        ).fetchall()

        findings = connection.execute(
            """
            SELECT backend, issue, evidence
            FROM snapshot_findings
            WHERE snapshot_id = ?
            ORDER BY backend, issue
            """,
            (snapshot_id,),
        ).fetchall()

        return {
            "id": snapshot["id"],
            "captured_at": snapshot["captured_at"],
            "threshold_ms": snapshot["threshold_ms"],
            "severity": snapshot["severity"],
            "source": snapshot["source"],
            "backends": [
                {
                    "name": row["backend"],
                    "healthy": bool(row["healthy"]),
                    "ewma_ms": row["ewma_ms"],
                }
                for row in backends
            ],
            "findings": [
                dict(row)
                for row in findings
            ],
        }


def list_snapshots(
    limit: int = 100,
    db_path=None,
) -> list[dict]:
    """Return recent snapshot metadata."""

    if not 1 <= limit <= 1000:
        raise ValueError("Limit must be between 1 and 1000")

    with connect(db_path) as connection:

        rows = connection.execute(
            """
            SELECT *
            FROM telemetry_snapshots
            ORDER BY captured_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

        return [dict(row) for row in rows]


def get_backend_history(
    backend: str,
    limit: int = 100,
    db_path=None,
) -> list[dict]:
    """Retrieve recent historical samples for a backend."""

    if not 1 <= limit <= 1000:
        raise ValueError("Limit must be between 1 and 1000")

    with connect(db_path) as connection:

        rows = connection.execute(
            """
            SELECT
                s.id AS snapshot_id,
                s.captured_at,
                s.threshold_ms,
                b.backend,
                b.healthy,
                b.ewma_ms
            FROM backend_samples AS b
            JOIN telemetry_snapshots AS s
                ON s.id = b.snapshot_id
            WHERE b.backend = ?
            ORDER BY s.captured_at DESC, s.id DESC
            LIMIT ?
            """,
            (backend, limit),
        ).fetchall()

        return [
            {
                **dict(row),
                "healthy": bool(row["healthy"]),
            }
            for row in rows
        ]
