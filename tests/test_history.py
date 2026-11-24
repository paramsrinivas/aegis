
"""Automated tests for historical incident intelligence."""

import asyncio
import sqlite3

import pytest

from unittest.mock import patch
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app, explain
from app.storage import (
    initialize_db,
    save_snapshot,
    get_snapshot,
    list_snapshots,
    get_backend_history,
)
from app.incidents import list_incidents, get_incident
from app.trends import get_backend_trends
from app.collector import collect_telemetry
from app.historical_context import enrich_incident
from app.evidence import build_evidence
from app.grounding import (
    build_reasoning_context,
    build_grounded_explanation,
)


def make_incident(
    latency=145.0,
    healthy=True,
    threshold=100.0,
    backend="backend2",
):
    findings = []

    if not healthy:
        issue = "unhealthy"
        evidence = "manager healthy=0"
        severity = "critical"

    elif latency is None:
        issue = "unknown_latency"
        evidence = "EWMA missing"
        severity = "unknown"

    elif latency > threshold:
        issue = "high_latency"
        evidence = f"EWMA {latency} ms > {threshold} ms"
        severity = "medium"

    else:
        issue = None
        severity = "none"

    if issue:
        findings.append({
            "backend": backend,
            "issue": issue,
            "evidence": evidence,
        })

    return {
        "severity": severity,
        "threshold_ms": threshold,
        "backends": [{
            "name": backend,
            "healthy": healthy,
            "ewma_ms": latency,
        }],
        "findings": findings,
        "source": "Aegis manager /weights",
        "limitations": [
            "Current telemetry is a single snapshot.",
            "Root cause is unconfirmed.",
        ],
        "actions_executed": [],
    }


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


# --------------------------------------------------
# Storage
# --------------------------------------------------

def test_snapshot_persistence():
    incident = make_incident()

    snapshot_id = save_snapshot(incident)
    stored = get_snapshot(snapshot_id)

    assert stored["id"] == snapshot_id
    assert stored["backends"] == incident["backends"]
    assert stored["findings"] == incident["findings"]
    assert stored["severity"] == "medium"
    assert stored["captured_at"]


def test_empty_database():
    assert list_snapshots() == []
    assert list_incidents() == []
    assert get_snapshot(999) is None
    assert get_incident(999) is None


def test_multiple_snapshots():
    first = save_snapshot(make_incident(120.0))
    second = save_snapshot(make_incident(150.0))

    assert first != second
    assert len(list_snapshots()) == 2


def test_backend_history_isolation():
    save_snapshot(make_incident(145.0))
    save_snapshot(
        make_incident(45.0, backend="backend1")
    )

    history = get_backend_history("backend2")

    assert len(history) == 1
    assert history[0]["backend"] == "backend2"
    assert history[0]["ewma_ms"] == 145.0


def test_history_limit():
    for latency in (110.0, 120.0, 130.0):
        save_snapshot(make_incident(latency))

    history = get_backend_history("backend2", 2)

    assert len(history) == 2


def test_transaction_rollback():
    incident = make_incident()

    incident["backends"].append(
        dict(incident["backends"][0])
    )

    with pytest.raises(sqlite3.IntegrityError):
        save_snapshot(incident)

    assert list_snapshots() == []
    assert list_incidents() == []
    assert get_backend_history("backend2") == []


@pytest.mark.parametrize(
    "threshold",
    [0, -1, float("inf"), float("nan"), True],
)
def test_invalid_storage_threshold(threshold):
    incident = make_incident()
    incident["threshold_ms"] = threshold

    with pytest.raises(ValueError):
        save_snapshot(incident)

    assert list_snapshots() == []


# --------------------------------------------------
# Collector
# --------------------------------------------------

def test_telemetry_collection():
    incident = make_incident()

    with patch(
        "app.main.investigate",
        return_value=incident,
    ):
        result = asyncio.run(collect_telemetry())

    assert result["status"] == "collected"
    assert result["backend_count"] == 1
    assert result["finding_count"] == 1
    assert result["actions_executed"] == []
    assert len(list_snapshots()) == 1


def test_failed_collection_does_not_persist():
    with patch(
        "app.main.investigate",
        side_effect=HTTPException(
            status_code=503,
            detail="Telemetry unavailable",
        ),
    ):
        with pytest.raises(HTTPException):
            asyncio.run(collect_telemetry())

    assert list_snapshots() == []


# --------------------------------------------------
# Incident lifecycle
# --------------------------------------------------

def test_incident_creation():
    snapshot_id = save_snapshot(make_incident())

    incidents = list_incidents("open")

    assert len(incidents) == 1
    assert incidents[0]["issue"] == "high_latency"
    assert incidents[0]["first_snapshot_id"] == snapshot_id
    assert incidents[0]["observation_count"] == 1


def test_incident_deduplication():
    first = save_snapshot(make_incident(120.0))
    last = save_snapshot(make_incident(160.0))

    incidents = list_incidents("open")

    assert len(incidents) == 1
    assert incidents[0]["observation_count"] == 2
    assert incidents[0]["first_snapshot_id"] == first
    assert incidents[0]["last_snapshot_id"] == last


def test_incident_resolution():
    save_snapshot(make_incident(145.0))
    recovery = save_snapshot(make_incident(80.0))

    assert list_incidents("open") == []

    resolved = list_incidents("resolved")

    assert len(resolved) == 1
    assert resolved[0]["resolved_snapshot_id"] == recovery
    assert resolved[0]["resolved_at"]


def test_incident_recurrence():
    save_snapshot(make_incident(145.0))
    save_snapshot(make_incident(80.0))
    save_snapshot(make_incident(155.0))

    incidents = list_incidents()

    assert len(incidents) == 2
    assert len(list_incidents("open")) == 1
    assert len(list_incidents("resolved")) == 1


def test_missing_latency_does_not_resolve_high_latency():
    save_snapshot(make_incident(145.0))
    save_snapshot(make_incident(None))

    issues = {
        item["issue"]
        for item in list_incidents("open")
    }

    assert "high_latency" in issues
    assert "unknown_latency" in issues


def test_missing_backend_does_not_resolve_incident():
    save_snapshot(make_incident(145.0))
    save_snapshot(
        make_incident(45.0, backend="backend1")
    )

    incidents = list_incidents("open")

    assert len(incidents) == 1
    assert incidents[0]["backend"] == "backend2"


def test_threshold_isolation():
    save_snapshot(make_incident(145.0))
    save_snapshot(
        make_incident(145.0, threshold=200.0)
    )

    incidents = list_incidents("open")

    assert len(incidents) == 1
    assert incidents[0]["threshold_ms"] == 100.0


def test_unhealthy_incident_recovery():
    save_snapshot(
        make_incident(None, healthy=False)
    )

    assert list_incidents("open")[0]["issue"] == "unhealthy"

    save_snapshot(make_incident(50.0))

    assert list_incidents("open") == []
    assert len(list_incidents("resolved")) == 1


def test_initialization_is_idempotent():
    save_snapshot(make_incident())

    initialize_db()
    initialize_db()

    incidents = list_incidents()

    assert len(incidents) == 1
    assert incidents[0]["observation_count"] == 1


# --------------------------------------------------
# Historical APIs
# --------------------------------------------------

def test_snapshot_api(client):
    snapshot_id = save_snapshot(make_incident())

    response = client.get("/snapshots")

    assert response.status_code == 200
    assert response.json()["count"] == 1

    response = client.get(
        f"/snapshots/{snapshot_id}"
    )

    assert response.status_code == 200
    assert response.json()["id"] == snapshot_id


def test_backend_history_api(client):
    save_snapshot(make_incident())

    response = client.get("/history/backend2")

    assert response.status_code == 200
    assert response.json()["count"] == 1


def test_incident_api(client):
    save_snapshot(make_incident())

    response = client.get("/incidents?status=open")

    assert response.status_code == 200
    assert response.json()["count"] == 1

    incident_id = response.json()["incidents"][0]["id"]

    response = client.get(
        f"/incidents/{incident_id}"
    )

    assert response.status_code == 200
    assert response.json()["id"] == incident_id


@pytest.mark.parametrize(
    "endpoint",
    ["/snapshots/999", "/incidents/999"],
)
def test_missing_record_api(client, endpoint):
    assert client.get(endpoint).status_code == 404


@pytest.mark.parametrize(
    "endpoint",
    [
        "/snapshots?limit=0",
        "/snapshots?limit=1001",
        "/history/backend2?limit=0",
        "/incidents?status=invalid",
        "/trends/backend2?threshold_ms=0",
        "/trends/backend2?threshold_ms=inf",
        "/trends/backend2?limit=1001",
    ],
)
def test_invalid_historical_api_input(client, endpoint):
    assert client.get(endpoint).status_code == 422


def test_historical_reads_do_not_collect(client):
    save_snapshot(make_incident())

    for endpoint in (
        "/snapshots",
        "/history/backend2",
        "/incidents",
        "/trends/backend2",
    ):
        assert client.get(endpoint).status_code == 200

    assert len(list_snapshots()) == 1


# --------------------------------------------------
# Trend analysis
# --------------------------------------------------

def test_repeated_threshold_violations():
    for latency in (120.0, 150.0, 180.0):
        save_snapshot(make_incident(latency))

    result = get_backend_trends("backend2")

    assert result["sample_count"] == 3
    assert result["threshold_violations"] == 3
    assert result["violation_rate_percent"] == 100.0
    assert result["latency"]["average_ms"] == 150.0
    assert result["latency"]["minimum_ms"] == 120.0
    assert result["latency"]["maximum_ms"] == 180.0
    assert result["pattern"] == "repeated_threshold_violation"


def test_mixed_threshold_violations():
    for latency in (80.0, 120.0, 100.0):
        save_snapshot(make_incident(latency))

    result = get_backend_trends("backend2")

    assert result["threshold_violations"] == 1
    assert result["violation_rate_percent"] == pytest.approx(
        100 / 3
    )


def test_custom_analysis_threshold():
    save_snapshot(make_incident(145.0))
    save_snapshot(make_incident(155.0))

    result = get_backend_trends("backend2", 200.0)

    assert result["threshold_violations"] == 0
    assert result["pattern"] == "no_observed_threshold_violation"


def test_insufficient_history():
    result = get_backend_trends("backend2")

    assert result["sample_count"] == 0
    assert result["latency"]["average_ms"] is None
    assert result["pattern"] == "insufficient_data"

    save_snapshot(make_incident())

    result = get_backend_trends("backend2")

    assert result["sample_count"] == 1
    assert result["pattern"] == "insufficient_data"


def test_invalid_latency_excluded_from_statistics():
    save_snapshot(make_incident(120.0))
    save_snapshot(make_incident(None))
    save_snapshot(
        make_incident(500.0, healthy=False)
    )

    result = get_backend_trends("backend2")

    assert result["sample_count"] == 3
    assert result["valid_latency_samples"] == 1
    assert result["missing_latency_samples"] == 1
    assert result["unhealthy_samples"] == 1
    assert result["latency"]["average_ms"] == 120.0


def test_trend_api(client):
    save_snapshot(make_incident(120.0))
    save_snapshot(make_incident(150.0))

    response = client.get("/trends/backend2")

    assert response.status_code == 200

    result = response.json()

    assert result["sample_count"] == 2
    assert result["root_cause_confirmed"] is False
    assert result["actions_executed"] == []


# --------------------------------------------------
# Historical evidence integration
# --------------------------------------------------

def test_historical_evidence_preserves_current_ids():
    save_snapshot(make_incident(120.0))
    save_snapshot(make_incident(150.0))

    incident = make_incident()
    original = build_evidence(incident)

    enriched = enrich_incident(incident)
    evidence = build_evidence(enriched)

    assert evidence[:len(original)] == original
    assert len(evidence) > len(original)
    assert enriched["historical_status"] == "available"
    assert "historical_context" not in incident


def test_historical_context_backend_isolation():
    save_snapshot(make_incident(150.0))
    save_snapshot(
        make_incident(180.0, backend="backend1")
    )

    enriched = enrich_incident(make_incident())

    assert len(enriched["historical_context"]) == 1
    assert enriched["historical_context"][0]["backend"] == "backend2"


def test_no_relevant_history():
    enriched = enrich_incident(make_incident())

    assert enriched["historical_context"] == []
    assert enriched["historical_status"] == "no_relevant_history"


def test_historical_storage_failure():
    incident = make_incident()

    with patch(
        "app.historical_context.get_backend_trends",
        side_effect=sqlite3.OperationalError(
            "Database unavailable"
        ),
    ):
        enriched = enrich_incident(incident)

    assert enriched["historical_status"] == "unavailable"
    assert enriched["historical_context"] == []
    assert enriched["findings"] == incident["findings"]


def test_history_available_in_reasoning_context():
    save_snapshot(make_incident())

    enriched = enrich_incident(make_incident())
    context = build_reasoning_context(enriched, [])

    assert any(
        fact["kind"] == "historical_observation"
        for fact in context["evidence"]
    )


@pytest.mark.parametrize(
    "include_current_finding",
    [False, True],
)
def test_historical_reference_rejected(
    include_current_finding,
):
    save_snapshot(make_incident())

    enriched = enrich_incident(make_incident())
    evidence = build_evidence(enriched)

    historical = next(
        item for item in evidence
        if item["kind"] == "historical_observation"
    )

    finding = next(
        item for item in evidence
        if item["kind"] == "finding"
    )

    references = [historical["id"]]

    if include_current_finding:
        references.append(finding["id"])

    with pytest.raises(ValueError):
        build_grounded_explanation(
            enriched,
            {
                "hypotheses": [{
                    "hypothesis_id": "resource_contention",
                    "backend": "backend2",
                    "evidence_ids": references,
                }]
            },
        )


@pytest.mark.parametrize("status", [502, 503])
def test_historical_fallback_consistency(status):
    save_snapshot(make_incident(120.0))
    save_snapshot(make_incident(150.0))

    incident = make_incident()

    def mock_explanation(enriched, runbooks):
        return build_grounded_explanation(
            enriched,
            {"hypotheses": []},
        )

    with patch(
        "app.main.investigate",
        return_value=incident,
    ):
        with patch(
            "app.ai.explain_with_gemini",
            side_effect=mock_explanation,
        ):
            success = asyncio.run(explain(100.0))

        with patch(
            "app.ai.explain_with_gemini",
            side_effect=HTTPException(
                status_code=status,
                detail="Simulated provider failure",
            ),
        ):
            fallback = asyncio.run(explain(100.0))

    normal = success["explanation"]
    degraded = fallback["explanation"]

    assert success["ai_generated"] is True
    assert fallback["ai_generated"] is False
    assert fallback["ai_status"] == "degraded"

    assert normal["evidence"] == degraded["evidence"]
    assert normal["observations"] == degraded["observations"]

    assert any(
        item["kind"] == "historical_observation"
        for item in degraded["evidence"]
    )

    assert degraded["grounding"]["root_cause_confirmed"] is False
    assert fallback["actions_executed"] == []
    assert len(list_snapshots()) == 2

