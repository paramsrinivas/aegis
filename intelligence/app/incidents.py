
"""Persistent incident lifecycle management."""

INCIDENT_SCHEMA = """
CREATE TABLE IF NOT EXISTS incidents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    backend TEXT NOT NULL,
    issue TEXT NOT NULL,
    threshold_ms REAL NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('open', 'resolved')
    ),
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    resolved_at TEXT,
    first_snapshot_id INTEGER NOT NULL,
    last_snapshot_id INTEGER NOT NULL,
    resolved_snapshot_id INTEGER,
    observation_count INTEGER NOT NULL DEFAULT 1,
    latest_evidence TEXT NOT NULL,

    FOREIGN KEY (first_snapshot_id)
        REFERENCES telemetry_snapshots(id),

    FOREIGN KEY (last_snapshot_id)
        REFERENCES telemetry_snapshots(id),

    FOREIGN KEY (resolved_snapshot_id)
        REFERENCES telemetry_snapshots(id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_open_incident
ON incidents(backend, issue, threshold_ms)
WHERE status = 'open';

CREATE INDEX IF NOT EXISTS idx_incident_status
ON incidents(status, last_seen_at);

CREATE TABLE IF NOT EXISTS processed_snapshots (
    snapshot_id INTEGER PRIMARY KEY,
    FOREIGN KEY (snapshot_id)
        REFERENCES telemetry_snapshots(id)
);
"""


def recovery_confirmed(issue, backend, threshold):
    """Require affirmative evidence before resolving."""

    healthy = backend["healthy"]
    latency = backend["ewma_ms"]

    if issue == "unhealthy":
        return healthy

    if issue == "high_latency":
        return (
            healthy
            and latency is not None
            and latency <= threshold
        )

    if issue == "unknown_latency":
        return healthy and latency is not None

    return False


def update_incidents(connection, snapshot_id):
    """Apply a stored snapshot to the incident lifecycle."""

    processed = connection.execute(
        """
        SELECT snapshot_id
        FROM processed_snapshots
        WHERE snapshot_id = ?
        """,
        (snapshot_id,),
    ).fetchone()

    if processed is not None:
        return

    snapshot = connection.execute(
        """
        SELECT *
        FROM telemetry_snapshots
        WHERE id = ?
        """,
        (snapshot_id,),
    ).fetchone()

    if snapshot is None:
        raise ValueError("Snapshot does not exist")

    timestamp = snapshot["captured_at"]
    threshold = snapshot["threshold_ms"]

    samples = connection.execute(
        """
        SELECT backend, healthy, ewma_ms
        FROM backend_samples
        WHERE snapshot_id = ?
        """,
        (snapshot_id,),
    ).fetchall()

    backends = {
        row["backend"]: {
            "healthy": bool(row["healthy"]),
            "ewma_ms": row["ewma_ms"],
        }
        for row in samples
    }

    findings = connection.execute(
        """
        SELECT backend, issue, evidence
        FROM snapshot_findings
        WHERE snapshot_id = ?
        """,
        (snapshot_id,),
    ).fetchall()

    active_findings = {
        (row["backend"], row["issue"])
        for row in findings
    }

    for finding in findings:

        backend = finding["backend"]
        issue = finding["issue"]

        existing = connection.execute(
            """
            SELECT id
            FROM incidents
            WHERE backend = ?
              AND issue = ?
              AND threshold_ms = ?
              AND status = 'open'
            """,
            (backend, issue, threshold),
        ).fetchone()

        if existing is None:

            connection.execute(
                """
                INSERT INTO incidents (
                    backend,
                    issue,
                    threshold_ms,
                    status,
                    first_seen_at,
                    last_seen_at,
                    first_snapshot_id,
                    last_snapshot_id,
                    observation_count,
                    latest_evidence
                )
                VALUES (?, ?, ?, 'open', ?, ?, ?, ?, 1, ?)
                """,
                (
                    backend,
                    issue,
                    threshold,
                    timestamp,
                    timestamp,
                    snapshot_id,
                    snapshot_id,
                    finding["evidence"],
                ),
            )

        else:

            connection.execute(
                """
                UPDATE incidents
                SET last_seen_at = ?,
                    last_snapshot_id = ?,
                    observation_count = observation_count + 1,
                    latest_evidence = ?
                WHERE id = ?
                """,
                (
                    timestamp,
                    snapshot_id,
                    finding["evidence"],
                    existing["id"],
                ),
            )

    open_incidents = connection.execute(
        """
        SELECT *
        FROM incidents
        WHERE status = 'open'
          AND threshold_ms = ?
        """,
        (threshold,),
    ).fetchall()

    for incident in open_incidents:

        backend = incident["backend"]
        issue = incident["issue"]

        if backend not in backends:
            continue

        if (backend, issue) in active_findings:
            continue

        if not recovery_confirmed(
            issue,
            backends[backend],
            threshold,
        ):
            continue

        connection.execute(
            """
            UPDATE incidents
            SET status = 'resolved',
                resolved_at = ?,
                resolved_snapshot_id = ?
            WHERE id = ?
            """,
            (
                timestamp,
                snapshot_id,
                incident["id"],
            ),
        )

    connection.execute(
        """
        INSERT INTO processed_snapshots (snapshot_id)
        VALUES (?)
        """,
        (snapshot_id,),
    )


def replay_snapshots(connection):
    """Process existing snapshots in insertion order."""

    rows = connection.execute(
        """
        SELECT s.id
        FROM telemetry_snapshots AS s
        LEFT JOIN processed_snapshots AS p
            ON p.snapshot_id = s.id
        WHERE p.snapshot_id IS NULL
        ORDER BY s.id ASC
        """
    ).fetchall()

    for row in rows:
        update_incidents(connection, row["id"])

    return len(rows)


def list_incidents(
    status=None,
    limit=100,
    db_path=None,
):
    """Retrieve persistent incident records."""

    from app.storage import connect

    if status not in (None, "open", "resolved"):
        raise ValueError("Invalid incident status")

    if not 1 <= limit <= 1000:
        raise ValueError("Invalid limit")

    with connect(db_path) as connection:

        if status is None:
            rows = connection.execute(
                """
                SELECT *
                FROM incidents
                ORDER BY last_seen_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        else:
            rows = connection.execute(
                """
                SELECT *
                FROM incidents
                WHERE status = ?
                ORDER BY last_seen_at DESC, id DESC
                LIMIT ?
                """,
                (status, limit),
            ).fetchall()

        return [dict(row) for row in rows]


def get_incident(incident_id: int, db_path=None):
    """Retrieve an individual persistent incident."""

    from app.storage import connect

    with connect(db_path) as connection:

        row = connection.execute(
            """
            SELECT *
            FROM incidents
            WHERE id = ?
            """,
            (incident_id,),
        ).fetchone()

        if row is None:
            return None

        return dict(row)

