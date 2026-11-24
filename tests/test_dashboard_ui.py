
"""Automated Streamlit dashboard interaction tests."""

from copy import deepcopy
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from streamlit.testing.v1 import AppTest

from dashboard.api import APIError
from app.grounding import build_grounded_explanation


APP_PATH = (
    Path(__file__).resolve().parents[1]
    / "dashboard"
    / "main.py"
)

TIMESTAMP = "2026-11-24T08:43:31+00:00"

INCIDENT = {
    "severity": "medium",
    "threshold_ms": 100.0,
    "backends": [
        {
            "name": "backend1",
            "healthy": True,
            "ewma_ms": 45.0,
        },
        {
            "name": "backend2",
            "healthy": True,
            "ewma_ms": 145.0,
        },
        {
            "name": "backend3",
            "healthy": True,
            "ewma_ms": 48.0,
        },
    ],
    "findings": [
        {
            "backend": "backend2",
            "issue": "high_latency",
            "evidence": "EWMA 145.0 ms > 100.0 ms",
        }
    ],
    "source": "Aegis manager /weights",
    "limitations": [
        "Current telemetry is a sampled observation.",
        "Telemetry does not establish root cause.",
    ],
    "actions_executed": [],
    "historical_context": [],
    "historical_status": "no_relevant_history",
}

SNAPSHOT = {
    "id": 1,
    "captured_at": TIMESTAMP,
    "threshold_ms": 100.0,
    "severity": "medium",
    "source": "Aegis manager /weights",
    "backends": INCIDENT["backends"],
    "findings": INCIDENT["findings"],
}

INCIDENT_RECORD = {
    "id": 1,
    "backend": "backend2",
    "issue": "high_latency",
    "threshold_ms": 100.0,
    "status": "open",
    "first_seen_at": TIMESTAMP,
    "last_seen_at": TIMESTAMP,
    "resolved_at": None,
    "first_snapshot_id": 1,
    "last_snapshot_id": 1,
    "resolved_snapshot_id": None,
    "observation_count": 4,
    "latest_evidence": "EWMA 145.0 ms > 100.0 ms",
}


def make_explanation(degraded=False):
    incident = deepcopy(INCIDENT)

    hypotheses = [] if degraded else [
        {
            "hypothesis_id": "resource_contention",
            "backend": "backend2",
            "evidence_ids": ["E008"],
        }
    ]

    explanation = build_grounded_explanation(
        incident,
        {"hypotheses": hypotheses},
    )

    if degraded:
        explanation["grounding"][
            "hypothesis_selection"
        ] = "unavailable"

    return {
        "incident": incident,
        "explanation": explanation,
        "runbooks": [
            {
                "id": "latency",
                "title": "Elevated backend latency",
                "source": "runbooks/latency.md",
            }
        ],
        "model": (
            None if degraded
            else "gemini-3.1-flash-lite"
        ),
        "ai_generated": not degraded,
        "ai_status": (
            "degraded" if degraded
            else "available"
        ),
        "fallback_reason": (
            "Simulated provider outage"
            if degraded else None
        ),
        "review_required": True,
        "actions_executed": [],
    }


@pytest.fixture
def api(monkeypatch):
    client = MagicMock()

    client.base_url = "http://test-api:8010"

    client.health.return_value = {
        "status": "ok"
    }

    client.investigate.return_value = deepcopy(
        INCIDENT
    )

    client.snapshots.return_value = {
        "count": 0,
        "limit": 100,
        "snapshots": [],
    }

    client.historical_backends.return_value = {
        "count": 0,
        "backends": [],
    }

    client.snapshot.return_value = deepcopy(
        SNAPSHOT
    )

    client.incidents.return_value = {
        "count": 1,
        "limit": 100,
        "status_filter": None,
        "incidents": [
            deepcopy(INCIDENT_RECORD)
        ],
    }

    client.incident.return_value = deepcopy(
        INCIDENT_RECORD
    )

    client.collect.return_value = {
        "status": "collected",
        "snapshot": {"id": 5},
        "actions_executed": [],
    }

    client.explain.return_value = (
        make_explanation()
    )

    monkeypatch.setattr(
        "dashboard.api.AegisClient",
        lambda: client,
    )

    return client


def launch():
    app = AppTest.from_file(
        str(APP_PATH),
        default_timeout=30,
    ).run()

    assert not app.exception, [
        item.message for item in app.exception
    ]

    return app


def button(app, label):
    return next(
        item for item in app.button
        if item.label == label
    )


def values(elements):
    return [item.value for item in elements]


def assert_no_exceptions(app):
    assert not app.exception, [
        item.message for item in app.exception
    ]


def test_dashboard_launch(api):
    app = launch()

    assert "Aegis AI" in values(app.title)


def test_all_four_sections(api):
    app = launch()

    assert [tab.label for tab in app.tabs] == [
        "Infrastructure Overview",
        "Historical Analytics",
        "Incident Management",
        "AI Investigation",
    ]


def test_api_connected(api):
    app = launch()

    assert "Aegis AI API connected" in values(
        app.success
    )


def test_unexpected_health_response(api):
    api.health.return_value = {
        "status": "unknown"
    }

    app = launch()

    assert "Unexpected API health response" in (
        values(app.warning)
    )


def test_connection_failure(api):
    api.health.side_effect = APIError(
        "Cannot connect to the Aegis AI API."
    )

    app = launch()

    assert any(
        "Cannot connect" in message
        for message in values(app.error)
    )


def test_live_diagnostics_requested(api):
    launch()

    api.investigate.assert_called_with(100.0)


def test_overview_metrics(api):
    app = launch()

    metrics = {
        item.label: item.value
        for item in app.metric
    }

    assert metrics["Total backends"] == "3"
    assert metrics["Healthy backends"] == "3/3"
    assert metrics["Elevated latency"] == "1"
    assert metrics["Severity"] == "MEDIUM"


def test_latency_chart_renders(api):
    app = launch()

    assert len(app.get("plotly_chart")) >= 1


def test_diagnostics_failure(api):
    api.investigate.side_effect = APIError(
        "API request failed with HTTP 503."
    )

    app = launch()

    assert any(
        "HTTP 503" in message
        for message in values(app.error)
    )


def test_no_implicit_collection(api):
    launch()

    api.collect.assert_not_called()


def test_collect_snapshot(api):
    app = launch()

    button(
        app,
        "Collect telemetry snapshot",
    ).click().run()

    assert_no_exceptions(app)

    api.collect.assert_called_once_with(100.0)

    assert "Snapshot #5 stored" in values(
        app.success
    )


def test_collection_failure(api):
    api.collect.side_effect = APIError(
        "Telemetry persistence unavailable"
    )

    app = launch()

    button(
        app,
        "Collect telemetry snapshot",
    ).click().run()

    assert_no_exceptions(app)

    assert any(
        "Telemetry persistence unavailable" in message
        for message in values(app.error)
    )


def test_refresh_diagnostics(api):
    app = launch()

    before = api.investigate.call_count

    button(
        app,
        "Refresh diagnostics",
    ).click().run()

    assert_no_exceptions(app)

    assert api.investigate.call_count > before

    api.collect.assert_not_called()
    api.explain.assert_not_called()


def test_threshold_change(api):
    app = launch()

    app.number_input[0].set_value(150.0).run()

    assert_no_exceptions(app)

    api.investigate.assert_called_with(150.0)


def test_empty_history(api):
    app = launch()

    assert any(
        "No stored telemetry" in message
        for message in values(app.info)
    )

    api.history.assert_not_called()
    api.trends.assert_not_called()


def test_history_failure(api):
    api.historical_backends.side_effect = APIError(
        "Historical storage unavailable"
    )

    app = launch()

    assert any(
        "Historical storage unavailable" in message
        for message in values(app.error)
    )


def test_incident_record_displayed(api):
    app = launch()

    assert "Incident #1" in values(
        app.subheader
    )

    api.incident.assert_called_with(1)


def test_open_incident_filter(api):
    app = launch()

    app.selectbox(
        key="incident_status_filter"
    ).select("Open").run()

    assert_no_exceptions(app)

    assert "Incident #1" in values(
        app.subheader
    )


def test_resolved_incident_empty_filter(api):
    app = launch()

    app.selectbox(
        key="incident_status_filter"
    ).select("Resolved").run()

    assert_no_exceptions(app)

    assert any(
        "No incidents match" in message
        for message in values(app.info)
    )


def test_supporting_snapshot(api):
    app = launch()

    app.button(
        key="load_snapshot_1"
    ).click().run()

    assert_no_exceptions(app)

    api.snapshot.assert_called_with(1)


def test_no_implicit_ai_request(api):
    launch()

    api.explain.assert_not_called()


def test_ai_investigation_success(api):
    app = launch()

    app.button(
        key="run_ai_investigation"
    ).click().run()

    assert_no_exceptions(app)

    api.explain.assert_called_once_with(100.0)

    assert (
        "Grounded AI investigation completed."
        in values(app.success)
    )


def test_ai_safety_indicators(api):
    app = launch()

    app.button(
        key="run_ai_investigation"
    ).click().run()

    assert_no_exceptions(app)

    assert (
        "Root cause remains unconfirmed."
        in values(app.warning)
    )

    assert "Human review required." in values(
        app.info
    )

    metrics = {
        item.label: item.value
        for item in app.metric
    }

    assert metrics["Actions executed"] == "0"


def test_ai_result_persists_on_rerun(api):
    app = launch()

    app.button(
        key="run_ai_investigation"
    ).click().run()

    app.run()

    assert_no_exceptions(app)

    api.explain.assert_called_once()

    assert (
        "Grounded AI investigation completed."
        in values(app.success)
    )


def test_evidence_filter_no_extra_ai_call(api):
    app = launch()

    app.button(
        key="run_ai_investigation"
    ).click().run()

    app.selectbox(
        key="investigation_evidence_kind"
    ).select("finding").run()

    assert_no_exceptions(app)

    api.explain.assert_called_once()

    assert app.selectbox(
        key="investigation_evidence_id"
    ).value == "E008"


def test_ai_threshold_change_warning(api):
    app = launch()

    app.button(
        key="run_ai_investigation"
    ).click().run()

    app.number_input[0].set_value(150.0).run()

    assert_no_exceptions(app)

    api.explain.assert_called_once()

    assert any(
        "threshold has changed" in message
        for message in values(app.warning)
    )


def test_ai_deterministic_fallback(api):
    api.explain.return_value = (
        make_explanation(degraded=True)
    )

    app = launch()

    app.button(
        key="run_ai_investigation"
    ).click().run()

    assert_no_exceptions(app)

    assert any(
        "AI provider unavailable" in message
        for message in values(app.warning)
    )

    metrics = {
        item.label: item.value
        for item in app.metric
    }

    assert metrics["Analysis mode"] == (
        "Deterministic"
    )

    assert metrics["Actions executed"] == "0"


def test_ai_request_failure(api):
    api.explain.side_effect = APIError(
        "The API request timed out."
    )

    app = launch()

    app.button(
        key="run_ai_investigation"
    ).click().run()

    assert_no_exceptions(app)

    assert any(
        "timed out" in message
        for message in values(app.error)
    )

    assert (
        "investigation_result"
        not in app.session_state
    )


@pytest.fixture
def populated_history(api):
    from app.trends import analyze_history

    samples = [
        {
            "snapshot_id": index,
            "captured_at": (
                f"2026-11-24T08:43:{index:02d}+00:00"
            ),
            "threshold_ms": 100.0,
            "backend": "backend2",
            "healthy": True,
            "ewma_ms": latency,
        }
        for index, latency in enumerate(
            [110.0, 130.0, 150.0, 170.0],
            start=1,
        )
    ]

    api.historical_backends.return_value = {
        "count": 2,
        "backends": [
            "backend2",
            "retired-backend",
        ],
    }

    def history(backend, limit=100):
        records = [
            item for item in samples
            if item["backend"] == backend
        ]

        records = list(reversed(records))[:limit]

        return {
            "backend": backend,
            "count": len(records),
            "limit": limit,
            "order": "newest_first",
            "samples": records,
        }

    def trends(
        backend,
        threshold_ms=100.0,
        limit=100,
    ):
        records = history(
            backend,
            limit,
        )["samples"]

        result = analyze_history(
            backend,
            records,
            threshold_ms,
        )

        result["limit"] = limit

        return result

    api.history.side_effect = history
    api.trends.side_effect = trends

    return samples


def test_populated_history_metrics(
    api, populated_history
):
    app = launch()

    metrics = {
        item.label: item.value
        for item in app.metric
    }

    assert metrics["Stored observations"] == "4"
    assert metrics["Minimum EWMA"] == "110.00 ms"
    assert metrics["Average EWMA"] == "140.00 ms"
    assert metrics["Maximum EWMA"] == "170.00 ms"
    assert metrics["Threshold violations"] == "4"
    assert metrics["Observed violation rate"] == "100.0%"
    assert metrics["Valid latency samples"] == "4"
    assert metrics["Healthy observation rate"] == "100.0%"


def test_populated_history_chart(
    api, populated_history
):
    app = launch()

    assert len(app.get("plotly_chart")) >= 2

    assert "Historical latency" in values(
        app.subheader
    )


def test_repeated_threshold_violation(
    api, populated_history
):
    app = launch()

    assert "Repeated threshold violations" in (
        values(app.warning)
    )


def test_historical_threshold_change(
    api, populated_history
):
    app = launch()

    app.number_input[0].set_value(140.0).run()

    assert_no_exceptions(app)

    api.trends.assert_called_with(
        "backend2",
        threshold_ms=140.0,
        limit=100,
    )

    metrics = {
        item.label: item.value
        for item in app.metric
    }

    assert metrics["Threshold violations"] == "2"
    assert metrics["Observed violation rate"] == "50.0%"

    assert "Intermittent threshold violations" in (
        values(app.warning)
    )


def test_historical_observation_limit(
    api, populated_history
):
    app = launch()

    app.selectbox(
        key="historical_limit"
    ).select(10).run()

    assert_no_exceptions(app)

    api.history.assert_called_with(
        "backend2",
        limit=10,
    )

    api.trends.assert_called_with(
        "backend2",
        threshold_ms=100.0,
        limit=10,
    )


def test_historical_backend_selection(
    api, populated_history
):
    app = launch()

    app.selectbox(
        key="historical_backend"
    ).select("retired-backend").run()

    assert_no_exceptions(app)

    api.history.assert_called_with(
        "retired-backend",
        limit=100,
    )

    assert "Insufficient historical data" in (
        values(app.info)
    )

    metrics = {
        item.label: item.value
        for item in app.metric
    }

    assert metrics["Stored observations"] == "0"
    assert metrics["Average EWMA"] == "Unavailable"


def test_history_discovery_avoids_snapshot_requests(
    api, populated_history
):
    launch()

    api.historical_backends.assert_called_once()

    api.snapshots.assert_not_called()
    api.snapshot.assert_not_called()


def test_history_interaction_no_ai_or_collection(
    api, populated_history
):
    app = launch()

    app.selectbox(
        key="historical_limit"
    ).select(25).run()

    assert_no_exceptions(app)

    api.explain.assert_not_called()
    api.collect.assert_not_called()


def test_history_sample_request_failure(
    api, populated_history
):
    api.history.side_effect = APIError(
        "Historical samples unavailable"
    )

    app = launch()

    assert "Historical samples unavailable" in (
        values(app.error)
    )


def test_history_trend_request_failure(
    api, populated_history
):
    api.trends.side_effect = APIError(
        "Historical trends unavailable"
    )

    app = launch()

    assert "Historical trends unavailable" in (
        values(app.error)
    )
