
"""Collect and persist validated Aegis telemetry."""

from fastapi.concurrency import run_in_threadpool

from app.storage import (
    initialize_db,
    save_snapshot,
    get_snapshot,
)


def persist_incident(
    incident: dict,
    db_path=None,
) -> dict:
    """Persist telemetry and return the stored snapshot."""

    initialize_db(db_path)

    snapshot_id = save_snapshot(
        incident,
        db_path,
    )

    snapshot = get_snapshot(
        snapshot_id,
        db_path,
    )

    if snapshot is None:
        raise RuntimeError(
            "Stored snapshot could not be retrieved"
        )

    return snapshot


async def collect_telemetry(
    threshold_ms: float = 100.0,
    db_path=None,
) -> dict:
    """Fetch live telemetry and persist a validated snapshot."""

    from app.main import investigate

    incident = await investigate(
        threshold_ms=threshold_ms
    )

    snapshot = await run_in_threadpool(
        persist_incident,
        incident,
        db_path,
    )

    return {
        "status": "collected",
        "snapshot": snapshot,
        "backend_count": len(snapshot["backends"]),
        "finding_count": len(snapshot["findings"]),
        "actions_executed": [],
    }

