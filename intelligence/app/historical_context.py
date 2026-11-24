
"""Enrich current diagnostics with historical telemetry."""

import logging
import sqlite3

from app.trends import get_backend_trends

logger = logging.getLogger(__name__)

HISTORY_LIMIT = 100


def enrich_incident(
    incident: dict,
    db_path=None,
) -> dict:
    """Attach historical context without changing live findings."""

    enriched = dict(incident)
    enriched["historical_context"] = []
    enriched["historical_status"] = "available"

    backends = sorted({
        finding["backend"]
        for finding in incident["findings"]
    })

    try:
        for backend in backends:

            trends = get_backend_trends(
                backend,
                incident["threshold_ms"],
                HISTORY_LIMIT,
                db_path,
            )

            if trends["sample_count"] == 0:
                continue

            enriched["historical_context"].append({
                "backend": backend,
                "threshold_ms": trends["threshold_ms"],
                "sample_count": trends["sample_count"],
                "valid_latency_samples": (
                    trends["valid_latency_samples"]
                ),
                "threshold_violations": (
                    trends["threshold_violations"]
                ),
                "violation_rate_percent": (
                    trends["violation_rate_percent"]
                ),
                "first_observed_at": (
                    trends["first_observed_at"]
                ),
                "last_observed_at": (
                    trends["last_observed_at"]
                ),
                "observed_duration_seconds": (
                    trends["observed_duration_seconds"]
                ),
                "latency": trends["latency"],
                "pattern": trends["pattern"],
                "evidence": trends["evidence"],
            })

    except (sqlite3.Error, OSError) as exc:

        logger.warning(
            "Historical context unavailable: type=%s",
            type(exc).__name__,
        )

        enriched["historical_context"] = []
        enriched["historical_status"] = "unavailable"

    if (
        enriched["historical_status"] == "available"
        and not enriched["historical_context"]
    ):
        enriched["historical_status"] = "no_relevant_history"

    return enriched

