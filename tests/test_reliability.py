
import asyncio
import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app import ai
from app.knowledge import retrieve
from app.main import explain


INCIDENT = {
    "severity": "medium",
    "threshold_ms": 100.0,
    "backends": [
        {
            "name": "backend2",
            "healthy": True,
            "ewma_ms": 145.0,
        }
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
        "Single snapshot; no historical trend",
        "Health and EWMA do not establish root cause",
    ],
    "actions_executed": [],
}


VALID_EXPLANATION = {
    "summary": "Backend2 exceeds the latency threshold.",
    "observations": [
        "Backend2 EWMA latency is 145.0 ms."
    ],
    "hypotheses": [
        "Backend2 may be experiencing resource contention."
    ],
    "recommended_checks": [
        "Inspect CPU and memory utilization."
    ],
    "uncertainty": "Root cause is unknown.",
}

VALID_MODEL_OUTPUT = {
    "hypotheses": [
        {
            "hypothesis_id": "resource_contention",
            "backend": "backend2",
            "evidence_ids": ["E003", "E004"],
        }
    ]
}


class ProviderError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__("Simulated provider error")


@pytest.fixture
def mock_gemini(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    with patch("google.genai.Client") as constructor:
        client = constructor.return_value.__enter__.return_value

        with patch("app.ai.time.sleep") as sleep:
            yield client.models.generate_content, sleep


def test_retrieval_excludes_irrelevant_runbooks():
    results = retrieve(INCIDENT["findings"])

    assert [r["id"] for r in results] == ["latency"]


def test_retrieval_multiple_issues():
    findings = [
        {"issue": "high_latency", "evidence": "EWMA 145 ms"},
        {"issue": "unhealthy", "evidence": "Health check failed"},
    ]

    results = retrieve(findings)

    assert {r["id"] for r in results} == {
        "latency",
        "unhealthy",
    }


def test_retrieval_unknown_issue():
    results = retrieve([
        {"issue": "unsupported_issue", "evidence": "EWMA"}
    ])

    assert results == []



def test_gemini_success(mock_gemini):
    generate, sleep = mock_gemini

    generate.return_value = MagicMock(
        text=json.dumps(VALID_MODEL_OUTPUT)
    )

    result = ai.explain_with_gemini(INCIDENT, [])

    assert result["grounding"]["observations"] == "deterministic"
    assert result["grounding"]["evidence_references_validated"] is True
    assert result["grounding"]["root_cause_confirmed"] is False

    assert result["hypotheses"] == [
        "backend2 may be experiencing resource contention."
    ]

    assert result["hypothesis_details"][0]["evidence_ids"] == [
        "E003", "E004"
    ]

    assert result["hypothesis_details"][0]["status"] == "unconfirmed"

    assert any(
        item["kind"] == "latency"
        and item["backend"] == "backend2"
        and item["value"] == 145.0
        for item in result["evidence"]
    )

    assert generate.call_count == 1
    sleep.assert_not_called()


def test_gemini_retry_then_success(mock_gemini):
    generate, sleep = mock_gemini

    generate.side_effect = [
        ProviderError(503),
        MagicMock(text=json.dumps(VALID_MODEL_OUTPUT)),
    ]

    result = ai.explain_with_gemini(INCIDENT, [])

    assert result["grounding"]["observations"] == "deterministic"
    assert result["grounding"]["evidence_references_validated"] is True
    assert result["grounding"]["root_cause_confirmed"] is False

    assert result["hypothesis_details"][0]["hypothesis_id"] == (
        "resource_contention"
    )

    assert result["hypothesis_details"][0]["status"] == "unconfirmed"

    assert generate.call_count == 2
    sleep.assert_called_once_with(1)


def test_gemini_retry_exhaustion(mock_gemini):
    generate, sleep = mock_gemini

    generate.side_effect = ProviderError(503)

    with pytest.raises(HTTPException) as error:
        ai.explain_with_gemini(INCIDENT, [])

    assert error.value.status_code == 503
    assert generate.call_count == 3
    assert sleep.call_count == 2
    assert [c.args[0] for c in sleep.call_args_list] == [1, 2]


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_gemini_non_retryable_error(mock_gemini, status):
    generate, sleep = mock_gemini

    generate.side_effect = ProviderError(status)

    with pytest.raises(HTTPException) as error:
        ai.explain_with_gemini(INCIDENT, [])

    assert error.value.status_code == 502
    assert generate.call_count == 1
    sleep.assert_not_called()


def test_gemini_invalid_json(mock_gemini):
    generate, sleep = mock_gemini

    generate.return_value = MagicMock(
        text="not valid JSON"
    )

    with pytest.raises(HTTPException) as error:
        ai.explain_with_gemini(INCIDENT, [])

    assert error.value.status_code == 502
    assert generate.call_count == 1
    sleep.assert_not_called()


def test_gemini_invalid_schema(mock_gemini):
    generate, sleep = mock_gemini

    generate.return_value = MagicMock(
        text=json.dumps({"summary": "Incomplete response"})
    )

    with pytest.raises(HTTPException) as error:
        ai.explain_with_gemini(INCIDENT, [])

    assert error.value.status_code == 502
    assert generate.call_count == 1
    sleep.assert_not_called()


@pytest.mark.parametrize("status", [502, 503])
def test_deterministic_fallback(status):
    with patch(
        "app.main.investigate",
        return_value=INCIDENT,
    ), patch(
        "app.ai.explain_with_gemini",
        side_effect=HTTPException(
            status_code=status,
            detail="Simulated provider failure",
        ),
    ):
        result = asyncio.run(explain(100.0))

    assert result["incident"] == INCIDENT
    assert result["ai_generated"] is False
    assert result["ai_status"] == "degraded"
    assert result["model"] is None
    assert result["review_required"] is True
    assert result["actions_executed"] == []
    assert result["explanation"]["hypotheses"] == []
    assert result["explanation"]["observations"]
    assert result["explanation"]["recommended_checks"]
    assert [r["id"] for r in result["runbooks"]] == ["latency"]


def test_explain_success():
    with patch(
        "app.main.investigate",
        return_value=INCIDENT,
    ), patch(
        "app.ai.explain_with_gemini",
        return_value=VALID_EXPLANATION,
    ):
        result = asyncio.run(explain(100.0))

    assert result["ai_generated"] is True
    assert result["ai_status"] == "available"
    assert result["fallback_reason"] is None
    assert result["explanation"] == VALID_EXPLANATION
    assert result["review_required"] is True
    assert result["actions_executed"] == []


def test_telemetry_failure_is_not_hidden():
    with patch(
        "app.main.investigate",
        side_effect=HTTPException(
            status_code=503,
            detail="Aegis telemetry unavailable",
        ),
    ), patch("app.ai.explain_with_gemini") as generate:

        with pytest.raises(HTTPException) as error:
            asyncio.run(explain(100.0))

    assert error.value.status_code == 503
    generate.assert_not_called()

