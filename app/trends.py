
"""Deterministic historical telemetry analysis."""

import math

from datetime import datetime
from statistics import mean

from app.storage import get_backend_history


def analyze_history(
    backend: str,
    samples: list[dict],
    threshold_ms: float = 100.0,
) -> dict:
    """Calculate bounded historical telemetry statistics."""

    if (
        isinstance(threshold_ms, bool)
        or not isinstance(threshold_ms, (int, float))
        or not math.isfinite(threshold_ms)
        or threshold_ms <= 0
    ):
        raise ValueError("Invalid latency threshold")

    ordered = sorted(
        samples,
        key=lambda item: (
            datetime.fromisoformat(item["captured_at"]),
            item["snapshot_id"],
        ),
    )

    total = len(ordered)

    healthy_count = sum(
        item["healthy"] for item in ordered
    )

    valid = [
        item for item in ordered
        if item["healthy"]
        and item["ewma_ms"] is not None
    ]

    latencies = [
        item["ewma_ms"] for item in valid
    ]

    violations = [
        item for item in valid
        if item["ewma_ms"] > threshold_ms
    ]

    valid_count = len(valid)
    violation_count = len(violations)

    missing_count = sum(
        item["ewma_ms"] is None
        for item in ordered
    )

    first_at = (
        ordered[0]["captured_at"]
        if ordered else None
    )

    last_at = (
        ordered[-1]["captured_at"]
        if ordered else None
    )

    duration = (
        (
            datetime.fromisoformat(last_at)
            - datetime.fromisoformat(first_at)
        ).total_seconds()
        if total >= 2 else None
    )

    change = (
        latencies[-1] - latencies[0]
        if valid_count >= 2 else None
    )

    change_percent = (
        change / latencies[0] * 100
        if change is not None
        and latencies[0] > 0
        else None
    )

    if valid_count < 2:
        pattern = "insufficient_data"

    elif violation_count == valid_count:
        pattern = "repeated_threshold_violation"

    elif violation_count > 0:
        pattern = "intermittent_threshold_violation"

    else:
        pattern = "no_observed_threshold_violation"

    evidence = []

    if total:
        evidence.append(
            f"Analyzed {total} stored observations "
            f"for {backend}."
        )

    if valid_count:
        evidence.append(
            f"{violation_count} of {valid_count} "
            f"healthy observations with available "
            f"latency exceeded {threshold_ms} ms."
        )

        evidence.append(
            f"Observed EWMA ranged from "
            f"{min(latencies):.2f} ms to "
            f"{max(latencies):.2f} ms."
        )

    if duration is not None:
        evidence.append(
            f"Observations span {duration:.2f} seconds."
        )

    if missing_count:
        evidence.append(
            f"{missing_count} observations had "
            "missing latency telemetry."
        )

    return {
        "backend": backend,
        "threshold_ms": threshold_ms,
        "sample_count": total,
        "valid_latency_samples": valid_count,
        "healthy_samples": healthy_count,
        "unhealthy_samples": total - healthy_count,
        "missing_latency_samples": missing_count,
        "health_rate_percent": (
            healthy_count / total * 100
            if total else None
        ),
        "telemetry_availability_percent": (
            (total - missing_count) / total * 100
            if total else None
        ),
        "first_observed_at": first_at,
        "last_observed_at": last_at,
        "observed_duration_seconds": duration,
        "latency": {
            "minimum_ms": (
                min(latencies) if latencies else None
            ),
            "maximum_ms": (
                max(latencies) if latencies else None
            ),
            "average_ms": (
                mean(latencies) if latencies else None
            ),
            "latest_valid_ms": (
                latencies[-1] if latencies else None
            ),
            "change_ms": change,
            "change_percent": change_percent,
        },
        "threshold_violations": violation_count,
        "violation_rate_percent": (
            violation_count / valid_count * 100
            if valid_count else None
        ),
        "pattern": pattern,
        "latest_observation": (
            ordered[-1] if ordered else None
        ),
        "evidence": evidence,
        "limitations": [
            "Statistics describe collected observations, "
            "not continuous monitoring.",
            "Latency statistics exclude unhealthy "
            "backends and missing latency values.",
            "Threshold violations are evaluated against "
            "the requested analysis threshold.",
            "Average EWMA is not average request latency.",
            "Observation rates are not uptime or SLA metrics.",
            "Historical observations do not establish "
            "root cause.",
        ],
        "root_cause_confirmed": False,
        "actions_executed": [],
    }


def get_backend_trends(
    backend: str,
    threshold_ms: float = 100.0,
    limit: int = 100,
    db_path=None,
) -> dict:
    """Retrieve and analyze historical backend telemetry."""

    samples = get_backend_history(
        backend,
        limit,
        db_path,
    )

    result = analyze_history(
        backend,
        samples,
        threshold_ms,
    )

    result["limit"] = limit

    return result

