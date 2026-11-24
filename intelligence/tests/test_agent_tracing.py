"""Verify tracing across the actual ADK workflow and service."""

import asyncio
import json
import logging
from unittest.mock import AsyncMock, patch

import pytest

from google.adk.models.llm_response import LlmResponse
from google.genai import types

from app.agents.workflow import run_diagnostic_workflow
from app.agent_service import explain_with_adk
from app.observability import diagnostic_trace


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


def trace_events(caplog):
    return [
        json.loads(record.message)
        for record in caplog.records
        if record.name == "aegis.diagnostics"
        and json.loads(record.message)["event"]
        == "diagnostic_stage"
    ]


def test_workflow_emits_stage_events(
    incident, caplog
):
    caplog.set_level(logging.INFO)

    def controlled_model(context, request):
        reasoning = json.loads(
            request.contents[-1].parts[0].text
        )
        candidate = reasoning["allowed_hypotheses"][0]

        selection = {
            "hypotheses": [{
                "hypothesis_id": candidate["hypothesis_id"],
                "backend": candidate["backend"],
                "evidence_ids": [
                    candidate["required_evidence_id"]
                ],
            }]
        }

        return LlmResponse(
            content=types.Content(
                role="model",
                parts=[types.Part(text=json.dumps(selection))],
            )
        )

    runbooks = [{
        "id": "latency",
        "title": "Elevated latency",
        "content": "Review observations.",
        "source": "runbooks/latency.md",
    }]

    metadata = {
        "mode": "semantic_coverage",
        "fallback": False,
        "reason": None,
    }

    with patch(
        "app.agents.retrieval.select_runbooks",
        return_value=(runbooks, metadata),
    ):
        with diagnostic_trace() as trace_id:
            result = asyncio.run(
                run_diagnostic_workflow(
                    incident,
                    before_model_callback=controlled_model,
                )
            )

    events = trace_events(caplog)

    assert {
        event["stage"]
        for event in events
        if event["status"] == "success"
    } >= {
        "triage",
        "retrieval",
        "grounding",
        "workflow",
    }

    assert all(
        event["trace_id"] == trace_id
        for event in events
    )

    assert all(
        event["duration_ms"] >= 0
        for event in events
    )

    assert result["review_required"] is True
    assert result["actions_executed"] == []


def test_missing_key_emits_fallback_trace(
    incident, monkeypatch, caplog
):
    caplog.set_level(logging.INFO)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    result = asyncio.run(explain_with_adk(incident))

    events = trace_events(caplog)

    assert {
        event["stage"]
        for event in events
    } >= {"request", "fallback"}

    assert len({
        event["trace_id"]
        for event in events
    }) == 1

    assert events[0]["trace_id"] is not None
    assert result["agent"]["fallback"] is True
    assert result["review_required"] is True
    assert result["actions_executed"] == []


def test_workflow_failure_emits_trace(
    incident, monkeypatch, caplog
):
    caplog.set_level(logging.INFO)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    with patch(
        "app.agents.workflow.run_diagnostic_workflow",
        new_callable=AsyncMock,
        side_effect=RuntimeError("sensitive-error-detail"),
    ):
        result = asyncio.run(explain_with_adk(incident))

    events = trace_events(caplog)

    assert {
        event["stage"]
        for event in events
    } >= {"request", "fallback"}

    assert len({
        event["trace_id"]
        for event in events
    }) == 1

    assert "sensitive-error-detail" not in caplog.text
    assert result["agent"]["fallback"] is True


def test_missing_key_outcome(
    incident, monkeypatch, caplog
):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    result = asyncio.run(explain_with_adk(incident))

    outcomes = [
        json.loads(record.message)
        for record in caplog.records
        if record.name == "aegis.diagnostics"
        and json.loads(record.message)["event"]
        == "diagnostic_outcome"
    ]

    assert len(outcomes) == 1
    assert outcomes[0]["ai_status"] == "degraded"
    assert outcomes[0]["reason"] == "missing_api_key"
    assert outcomes[0]["fallback"] is True
    assert result["agent"]["fallback"] is True


def test_provider_failure_outcome(
    incident, monkeypatch, caplog
):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    class ProviderUnavailable(Exception):
        code = 503

    with patch(
        "app.agents.workflow.run_diagnostic_workflow",
        new_callable=AsyncMock,
        side_effect=ProviderUnavailable(
            "sensitive-provider-response"
        ),
    ):
        result = asyncio.run(explain_with_adk(incident))

    outcomes = [
        json.loads(record.message)
        for record in caplog.records
        if record.name == "aegis.diagnostics"
        and json.loads(record.message)["event"]
        == "diagnostic_outcome"
    ]

    assert len(outcomes) == 1
    assert outcomes[0]["reason"] == "provider_unavailable"
    assert outcomes[0]["fallback"] is True
    assert result["ai_status"] == "degraded"
    assert "sensitive-provider-response" not in caplog.text
