"""ADK service and HTTP endpoint integration tests."""

import asyncio
from unittest.mock import patch, AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.agent_service import explain_with_adk
from app.grounding import build_grounded_explanation


@pytest.fixture
def incident():
    return {
        "threshold_ms": 100.0,
        "severity": "medium",
        "backends": [{
            "name": "backend1",
            "healthy": True,
            "ewma_ms": 180.0,
        }],
        "findings": [{
            "backend": "backend1",
            "issue": "high_latency",
            "evidence": "Latency exceeds threshold.",
        }],
        "limitations": [],
    }


def workflow_result(incident):
    return {
        "explanation": build_grounded_explanation(
            incident,
            {"hypotheses": []},
        ),
        "runbooks": [{
            "id": "latency",
            "title": "Elevated latency",
            "content": "Inspect repeated measurements.",
            "source": "runbooks/latency.md",
        }],
        "retrieval": {
            "mode": "semantic_coverage",
            "fallback": False,
            "reason": None,
        },
        "review_required": True,
        "actions_executed": [],
    }


def test_service_success(incident, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_MODEL", "test-model")

    with patch(
        "app.agents.workflow.run_diagnostic_workflow",
        new_callable=AsyncMock,
        return_value=workflow_result(incident),
    ) as workflow:
        result = asyncio.run(explain_with_adk(incident))

    workflow.assert_awaited_once()

    args = workflow.await_args.args
    kwargs = workflow.await_args.kwargs

    assert args == (incident,)
    assert kwargs["model"].model == "test-model"
    assert kwargs["model"].client is not None

    assert result["ai_generated"] is True
    assert result["ai_status"] == "available"
    assert result["model"] == "test-model"
    assert result["agent"]["fallback"] is False
    assert result["fallback_reason"] is None


@pytest.mark.parametrize(
    "failure",
    [
        RuntimeError("Model unavailable"),
        TimeoutError("Workflow timeout"),
        ValueError("Invalid evidence"),
    ],
)
def test_service_fallback(
    incident, monkeypatch, failure
):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    with patch(
        "app.agents.workflow.run_diagnostic_workflow",
        new_callable=AsyncMock,
        side_effect=failure,
    ):
        result = asyncio.run(explain_with_adk(incident))

    assert result["ai_generated"] is False
    assert result["ai_status"] == "degraded"
    assert result["model"] is None
    assert result["agent"]["fallback"] is True
    assert result["review_required"] is True
    assert result["actions_executed"] == []
    assert result["runbooks"]
    assert result["explanation"]["observations"]
    assert result["explanation"]["hypothesis_details"] == []

    assert result["explanation"]["grounding"][
        "root_cause_confirmed"
    ] is False

    assert result["explanation"]["grounding"][
        "hypothesis_selection"
    ] == "unavailable"


def test_missing_key(incident, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with patch(
        "app.agents.workflow.run_diagnostic_workflow",
        new_callable=AsyncMock,
    ) as workflow:
        result = asyncio.run(explain_with_adk(incident))

    workflow.assert_not_awaited()

    assert result["ai_generated"] is False
    assert result["agent"]["fallback"] is True


def test_adk_endpoint_success(incident, monkeypatch):
    monkeypatch.setenv("AEGIS_AGENT_MODE", "adk")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    with (
        patch(
            "app.main.investigate",
            new_callable=AsyncMock,
            return_value=incident,
        ),
        patch(
            "app.historical_context.enrich_incident",
            return_value=incident,
        ),
        patch(
            "app.agents.workflow.run_diagnostic_workflow",
            new_callable=AsyncMock,
            return_value=workflow_result(incident),
        ) as workflow,
        patch(
            "app.ai.explain_with_gemini",
        ) as legacy,
    ):
        response = TestClient(app).get("/explain")

    assert response.status_code == 200

    data = response.json()

    workflow.assert_awaited_once()
    legacy.assert_not_called()

    assert data["incident"] == incident
    assert data["agent"]["mode"] == "adk"
    assert data["agent"]["fallback"] is False
    assert data["ai_generated"] is True
    assert data["review_required"] is True
    assert data["actions_executed"] == []
    assert data["retrieval"]["mode"] == "semantic_coverage"

    assert set(data["runbooks"][0]) == {
        "id", "title", "source"
    }


def test_adk_endpoint_failure(incident, monkeypatch):
    monkeypatch.setenv("AEGIS_AGENT_MODE", "adk")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    with (
        patch(
            "app.main.investigate",
            new_callable=AsyncMock,
            return_value=incident,
        ),
        patch(
            "app.historical_context.enrich_incident",
            return_value=incident,
        ),
        patch(
            "app.agents.workflow.run_diagnostic_workflow",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Unavailable"),
        ),
    ):
        response = TestClient(app).get("/explain")

    assert response.status_code == 200

    data = response.json()

    assert data["ai_generated"] is False
    assert data["ai_status"] == "degraded"
    assert data["agent"]["fallback"] is True
    assert data["review_required"] is True
    assert data["actions_executed"] == []
    assert data["explanation"]["observations"]


def test_legacy_endpoint_preserved(incident, monkeypatch):
    monkeypatch.delenv("AEGIS_AGENT_MODE", raising=False)
    monkeypatch.setenv("AEGIS_RAG_MODE", "off")

    explanation = build_grounded_explanation(
        incident,
        {"hypotheses": []},
    )

    with (
        patch(
            "app.main.investigate",
            new_callable=AsyncMock,
            return_value=incident,
        ),
        patch(
            "app.historical_context.enrich_incident",
            return_value=incident,
        ),
        patch(
            "app.ai.explain_with_gemini",
            return_value=explanation,
        ) as legacy,
        patch(
            "app.agent_service.explain_with_adk",
            new_callable=AsyncMock,
        ) as adk,
    ):
        response = TestClient(app).get("/explain")

    assert response.status_code == 200

    data = response.json()

    legacy.assert_called_once()
    adk.assert_not_awaited()

    assert "agent" not in data
    assert "retrieval" not in data
    assert data["ai_generated"] is True
    assert data["review_required"] is True
    assert data["actions_executed"] == []
