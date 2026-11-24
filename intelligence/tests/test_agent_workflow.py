"""End-to-end ADK diagnostic workflow tests."""

import asyncio
import json
from unittest.mock import patch

import pytest

from google.adk.models.llm_response import LlmResponse
from google.genai import types

from app.agents.workflow import run_diagnostic_workflow


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


def execute(incident, transform=None):
    calls = []

    runbooks = [{
        "id": "latency",
        "title": "Elevated latency",
        "content": "Inspect repeated measurements.",
        "source": "runbooks/latency.md",
    }]

    metadata = {
        "mode": "semantic_coverage",
        "fallback": False,
        "reason": None,
    }

    def mock_model(context, request):
        calls.append(request)

        payload = json.loads(
            request.contents[-1].parts[0].text
        )

        assert payload["runbooks"] == runbooks
        assert payload["severity"] == incident["severity"]

        candidate = payload["allowed_hypotheses"][0]

        selection = {
            "hypotheses": [{
                "hypothesis_id": candidate["hypothesis_id"],
                "backend": candidate["backend"],
                "evidence_ids": [
                    candidate["required_evidence_id"]
                ],
            }]
        }

        if transform is not None:
            selection = transform(selection)

        return LlmResponse(
            content=types.Content(
                role="model",
                parts=[
                    types.Part(
                        text=json.dumps(selection)
                    )
                ],
            )
        )

    with patch(
        "app.agents.retrieval.select_runbooks",
        return_value=(runbooks, metadata),
    ) as retrieve:

        result = asyncio.run(
            run_diagnostic_workflow(
                incident,
                before_model_callback=mock_model,
            )
        )

    assert len(calls) == 1
    retrieve.assert_called_once_with(incident)

    return result


def test_complete_workflow(incident):
    result = execute(incident)

    assert result["review_required"] is True
    assert result["actions_executed"] == []

    assert result["retrieval"]["mode"] == (
        "semantic_coverage"
    )

    explanation = result["explanation"]

    assert len(explanation["hypothesis_details"]) == 1

    assert explanation["grounding"][
        "evidence_references_validated"
    ] is True

    assert explanation["grounding"][
        "root_cause_confirmed"
    ] is False


def test_empty_selection(incident):
    result = execute(
        incident,
        lambda selection: {"hypotheses": []},
    )

    assert result["explanation"]["hypothesis_details"] == []
    assert result["explanation"]["observations"]


def test_invalid_evidence_rejected(incident):
    def corrupt(selection):
        selection["hypotheses"][0]["evidence_ids"] = [
            "E999"
        ]
        return selection

    with pytest.raises(ValueError, match="Unknown evidence"):
        execute(incident, corrupt)
