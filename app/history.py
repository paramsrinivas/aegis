
"""Read-only historical telemetry and incident APIs."""

import logging
import sqlite3

from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Query, Path

from app.storage import (
    list_snapshots,
    get_snapshot,
    get_backend_history,
)

from app.incidents import (
    list_incidents,
    get_incident,
)


router = APIRouter(tags=["Historical intelligence"])

logger = logging.getLogger(__name__)


def read_storage(operation, *args, **kwargs):
    """Translate storage failures into controlled API errors."""

    try:
        return operation(*args, **kwargs)

    except (sqlite3.Error, OSError) as exc:

        logger.error(
            "Historical storage read failed: type=%s",
            type(exc).__name__,
        )

        raise HTTPException(
            status_code=503,
            detail="Historical storage unavailable",
        ) from exc


@router.get("/snapshots")
def snapshots(
    limit: int = Query(100, ge=1, le=1000),
):
    """List recent telemetry snapshots."""

    records = read_storage(
        list_snapshots,
        limit,
    )

    return {
        "count": len(records),
        "limit": limit,
        "snapshots": records,
    }


@router.get("/snapshots/{snapshot_id}")
def snapshot_details(
    snapshot_id: int = Path(..., ge=1),
):
    """Retrieve a complete historical snapshot."""

    record = read_storage(
        get_snapshot,
        snapshot_id,
    )

    if record is None:
        raise HTTPException(
            status_code=404,
            detail="Snapshot not found",
        )

    return record


@router.get("/history/{backend}")
def backend_history(
    backend: str = Path(
        ...,
        min_length=1,
        max_length=255,
    ),
    limit: int = Query(100, ge=1, le=1000),
):
    """Retrieve historical telemetry for a backend."""

    records = read_storage(
        get_backend_history,
        backend,
        limit,
    )

    return {
        "backend": backend,
        "count": len(records),
        "limit": limit,
        "order": "newest_first",
        "samples": records,
    }


@router.get("/incidents")
def incidents(
    status: Optional[
        Literal["open", "resolved"]
    ] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
):
    """List persistent incidents with optional filtering."""

    records = read_storage(
        list_incidents,
        status,
        limit,
    )

    return {
        "count": len(records),
        "limit": limit,
        "status_filter": status,
        "incidents": records,
    }


@router.get("/incidents/{incident_id}")
def incident_details(
    incident_id: int = Path(..., ge=1),
):
    """Retrieve an individual persistent incident."""

    record = read_storage(
        get_incident,
        incident_id,
    )

    if record is None:
        raise HTTPException(
            status_code=404,
            detail="Incident not found",
        )

    return record


@router.get("/trends/{backend}")
def backend_trends(
    backend: str = Path(
        ...,
        min_length=1,
        max_length=255,
    ),
    threshold_ms: float = Query(
        100.0,
        gt=0,
        allow_inf_nan=False,
    ),
    limit: int = Query(
        100,
        ge=1,
        le=1000,
    ),
):
    """Calculate deterministic historical trends."""

    from app.trends import get_backend_trends

    return read_storage(
        get_backend_trends,
        backend,
        threshold_ms,
        limit,
    )

