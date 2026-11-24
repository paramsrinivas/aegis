"""Safety and isolation tests for ADK diagnostics."""

import asyncio
import json
from copy import deepcopy
from unittest.mock import patch

import pytest

from google.adk.models.llm_response import LlmResponse
from google.genai import types

from app.agents.workflow import run_diagnostic_workflow


def make_incident(backend):
    return {
        "threshold_ms": 100.0,
        "severity": "medium",
        "backends": [{
            "name": backend,
            "healthy": True,
            "ewma_ms": 180.0,
        }],
        "findings": [{
            "backend": backend,
            "issue": "high_latency",
            "evidence": "Latency exceeds threshold.",
        }],
        "limitations": [],
    }


def model_response(payload):
    return LlmResponse(
        content=types.Content(
            role="model",
            parts=[
                types.Part(text=json.dumps(payload))
            ],
        ),
    )


def valid_selection(request):
    context = json.loads(
        request.contents[-1].parts[0].text
    )

    candidate = context["allowed_hypotheses"][0]

    return {
        "hypotheses": [{
            "hypothesis_id": candidate["hypothesis_id"],
            "backend": candidate["backend"],
            "evidence_ids": [
                candidate["required_evidence_id"]
            ],
        }]
    }


def execute(incident, callback):
    with patch(
        "app.agents.retrieval.select_runbooks",
        return_value=([], None),
    ):
        return asyncio.run(
            run_diagnostic_workflow(
                incident,
                before_model_callback=callback,
            )
        )


def test_concurrent_session_isolation():
    calls = []

    async def mock_model(context, request):
        selection = valid_selection(request)

        calls.append(
            selection["hypotheses"][0]["backend"]
        )

        await asyncio.sleep(0.02)

        return model_response(selection)

    async def run():
        return await asyncio.gather(
            run_diagnostic_workflow(
                make_incident("backend1"),
                before_model_callback=mock_model,
            ),
            run_diagnostic_workflow(
                make_incident("backend2"),
                before_model_callback=mock_model,
            ),
        )

    with patch(
        "app.agents.retrieval.select_runbooks",
        return_value=([], None),
    ):
        first, second = asyncio.run(run())

    assert sorted(calls) == ["backend1", "backend2"]

    assert first["explanation"][
        "hypothesis_details"
    ][0]["backend"] == "backend1"

    assert second["explanation"][
        "hypothesis_details"
    ][0]["backend"] == "backend2"

    for result in (first, second):
        assert result["review_required"] is True
        assert result["actions_executed"] == []


def test_incident_not_modified():
    incident = make_incident("backend1")
    original = deepcopy(incident)

    def mock_model(context, request):
        return model_response(
            valid_selection(request)
        )

    execute(incident, mock_model)

    assert incident == original


def test_reject_cross_backend_selection():
    def mock_model(context, request):
        selection = valid_selection(request)

        selection["hypotheses"][0]["backend"] = (
            "backend2"
        )

        return model_response(selection)

    with pytest.raises(ValueError):
        execute(
            make_incident("backend1"),
            mock_model,
        )


def test_reject_unsupported_hypothesis():
    def mock_model(context, request):
        selection = valid_selection(request)

        selection["hypotheses"][0][
            "hypothesis_id"
        ] = "application_failure"

        return model_response(selection)

    with pytest.raises(ValueError):
        execute(
            make_incident("backend1"),
            mock_model,
        )


def test_reject_duplicate_hypotheses():
    def mock_model(context, request):
        selection = valid_selection(request)

        selection["hypotheses"].append(
            deepcopy(selection["hypotheses"][0])
        )

        return model_response(selection)

    with pytest.raises(ValueError):
        execute(
            make_incident("backend1"),
            mock_model,
        )


def test_model_failure_propagates():
    def mock_model(context, request):
        raise RuntimeError("Simulated model failure")

    with pytest.raises(
        RuntimeError,
        match="Simulated model failure",
    ):
        execute(
            make_incident("backend1"),
            mock_model,
        )


def test_workflow_timeout():
    async def slow_model(context, request):
        await asyncio.sleep(5)

        return model_response(
            {"hypotheses": []}
        )

    with patch(
        "app.agents.workflow.WORKFLOW_TIMEOUT_SECONDS",
        0.1,
    ):
        with pytest.raises(TimeoutError):
            execute(
                make_incident("backend1"),
                slow_model,
            )


def test_retrieval_fallback_preserved():
    metadata = {
        "mode": "deterministic_fallback",
        "fallback": True,
        "reason": "rag_unavailable",
    }

    def mock_model(context, request):
        return model_response(
            valid_selection(request)
        )

    with patch(
        "app.agents.retrieval.select_runbooks",
        return_value=([], metadata),
    ):
        result = asyncio.run(
            run_diagnostic_workflow(
                make_incident("backend1"),
                before_model_callback=mock_model,
            )
        )

    assert result["retrieval"] == metadata
    assert result["review_required"] is True
    assert result["actions_executed"] == []


def test_reject_extra_model_output_fields():
    def mock_model(context, request):
        selection = valid_selection(request)
        selection["actions"] = ["restart_backend"]

        return model_response(selection)

    with pytest.raises(ValueError):
        execute(
            make_incident("backend1"),
            mock_model,
        )


def test_reject_extra_model_hypothesis_fields():
    def mock_model(context, request):
        selection = valid_selection(request)

        selection["hypotheses"][0][
            "root_cause_confirmed"
        ] = True

        return model_response(selection)

    with pytest.raises(ValueError):
        execute(
            make_incident("backend1"),
            mock_model,
        )


def test_reject_malformed_model_json():
    def mock_model(context, request):
        return LlmResponse(
            content=types.Content(
                role="model",
                parts=[
                    types.Part(text="not valid JSON")
                ],
            ),
        )

    with pytest.raises(ValueError):
        execute(
            make_incident("backend1"),
            mock_model,
        )


def test_reject_non_string_model_evidence():
    def mock_model(context, request):
        selection = valid_selection(request)

        selection["hypotheses"][0]["evidence_ids"] = [
            123
        ]

        return model_response(selection)

    with pytest.raises(ValueError):
        execute(
            make_incident("backend1"),
            mock_model,
        )
