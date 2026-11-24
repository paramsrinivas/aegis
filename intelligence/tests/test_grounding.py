
import asyncio
import json
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.ai import explain_with_gemini
from app.evidence import (
    build_evidence,
    validate_evidence_references,
    grounded_observations,
)
from app.reasoning import validate_hypotheses
from app.grounding import (
    build_reasoning_context,
    build_grounded_explanation,
)
from app.main import explain


@pytest.fixture
def incident():
    return {
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
        "limitations": [
            "Single snapshot; no historical trend",
            "Health and EWMA do not establish root cause",
        ],
        "source": "Aegis manager /weights",
        "actions_executed": [],
    }


@pytest.fixture
def selection():
    return {
        "hypothesis_id": "resource_contention",
        "backend": "backend2",
        "evidence_ids": ["E003", "E004"],
    }


def test_evidence_registry(incident):
    evidence = build_evidence(incident)

    assert len(evidence) == 7
    assert len({item["id"] for item in evidence}) == 7

    assert evidence[2]["kind"] == "latency"
    assert evidence[2]["value"] == 145.0
    assert evidence[2]["backend"] == "backend2"


def test_evidence_is_deterministic(incident):
    assert build_evidence(incident) == build_evidence(incident)


def test_grounded_observations(incident):
    observations = grounded_observations(
        build_evidence(incident)
    )

    assert len(observations) == 5

    assert (
        "[E003] backend2 EWMA latency is 145.00 ms."
        in observations
    )


def test_valid_evidence_references(incident):
    references = ["E003", "E004"]

    assert validate_evidence_references(
        references,
        build_evidence(incident),
    ) == references


@pytest.mark.parametrize("references", [
    [],
    ["E999"],
    ["E003", "E003"],
    [123],
    "E003",
    None,
])
def test_invalid_evidence_references(
    incident, references
):
    with pytest.raises(ValueError):
        validate_evidence_references(
            references,
            build_evidence(incident),
        )


def test_valid_hypothesis(incident, selection):
    result = validate_hypotheses(
        [selection],
        build_evidence(incident),
    )

    assert len(result) == 1
    assert result[0]["status"] == "unconfirmed"

    assert result[0]["statement"] == (
        "backend2 may be experiencing resource contention."
    )


@pytest.mark.parametrize("override", [
    {"hypothesis_id": "invented_root_cause"},
    {"hypothesis_id": "application_failure"},
    {"backend": "backend99"},
    {"backend": ""},
    {"backend": 123},
    {"evidence_ids": ["E999"]},
    {"evidence_ids": ["E003"]},
    {"evidence_ids": ["E001", "E004"]},
    {"evidence_ids": ["E003", "E004", "E007"]},
    {"evidence_ids": []},
    {"statement": "CPU utilization is 95%"},
    {"status": "confirmed"},
    {"hypothesis_id": None},
])
def test_adversarial_hypotheses(
    incident, selection, override
):
    candidate = {**selection, **override}

    with pytest.raises(ValueError):
        validate_hypotheses(
            [candidate],
            build_evidence(incident),
        )


def test_duplicate_hypotheses(incident, selection):
    with pytest.raises(ValueError):
        validate_hypotheses(
            [selection, selection],
            build_evidence(incident),
        )


def test_hypothesis_limit(incident, selection):
    with pytest.raises(ValueError):
        validate_hypotheses(
            [selection] * 11,
            build_evidence(incident),
        )


def test_cross_backend_evidence(incident, selection):
    evidence = build_evidence(incident)

    evidence.append({
        "id": "E008",
        "kind": "latency",
        "backend": "backend3",
        "value": 50.0,
        "statement": "backend3 latency is 50 ms.",
    })

    candidate = {
        **selection,
        "evidence_ids": ["E004", "E008"],
    }

    with pytest.raises(ValueError):
        validate_hypotheses(
            [candidate],
            evidence,
        )


def test_reasoning_context(incident):
    context = build_reasoning_context(incident, [])

    candidates = context["allowed_hypotheses"]

    assert len(candidates) == 4

    assert {
        item["hypothesis_id"] for item in candidates
    } == {
        "resource_contention",
        "increased_load",
        "dependency_latency",
        "transient_degradation",
    }

    assert all(
        item["backend"] == "backend2"
        and item["required_evidence_id"] == "E004"
        for item in candidates
    )


def test_grounded_explanation(incident, selection):
    result = build_grounded_explanation(
        incident,
        {"hypotheses": [selection]},
    )

    assert result["evidence"] == build_evidence(incident)

    assert result["grounding"]["observations"] == (
        "deterministic"
    )

    assert result["grounding"][
        "evidence_references_validated"
    ] is True

    assert result["grounding"][
        "root_cause_confirmed"
    ] is False

    assert result["hypothesis_details"][0][
        "status"
    ] == "unconfirmed"

    assert result["recommended_checks"]


@pytest.mark.parametrize("extra", [
    {"observations": ["CPU utilization is 95%"]},
    {"summary": "Confirmed database failure"},
    {"root_cause": "Memory exhaustion"},
    {"recommended_checks": ["Restart all backends"]},
    {"actions_executed": ["Restarted backend2"]},
    {"severity": "critical"},
])
def test_injected_model_fields(
    incident, selection, extra
):
    output = {
        "hypotheses": [selection],
        **extra,
    }

    with pytest.raises(ValueError):
        build_grounded_explanation(
            incident, output
        )


@pytest.mark.parametrize("output", [
    None,
    [],
    {},
    {"hypotheses": "resource_contention"},
    {"hypotheses": [None]},
    {"hypotheses": ["CPU failure"]},
])
def test_malformed_model_output(incident, output):
    with pytest.raises(ValueError):
        build_grounded_explanation(
            incident, output
        )


def test_empty_hypothesis_selection(incident):
    result = build_grounded_explanation(
        incident,
        {"hypotheses": []},
    )

    assert result["hypotheses"] == []
    assert result["hypothesis_details"] == []
    assert result["recommended_checks"]
    assert result["evidence"]


def test_normal_operation(incident):
    incident["severity"] = "none"
    incident["findings"] = []
    incident["backends"][0]["ewma_ms"] = 50.0

    context = build_reasoning_context(
        incident, []
    )

    assert context["allowed_hypotheses"] == []

    result = build_grounded_explanation(
        incident,
        {"hypotheses": []},
    )

    assert result["hypotheses"] == []

    assert result["recommended_checks"] == [
        "Continue monitoring backend health and latency."
    ]


@pytest.mark.parametrize("status", [502, 503])
def test_grounded_fallback_consistency(
    incident, selection, status
):
    grounded = build_grounded_explanation(
        incident,
        {"hypotheses": [selection]},
    )

    with patch(
        "app.main.investigate",
        return_value=incident,
    ):
        with patch(
            "app.ai.explain_with_gemini",
            return_value=grounded,
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

    assert set(success) == set(fallback)
    assert set(normal) == set(degraded)

    assert normal["evidence"] == degraded["evidence"]

    assert normal["observations"] == (
        degraded["observations"]
    )

    assert fallback["ai_generated"] is False
    assert fallback["ai_status"] == "degraded"
    assert fallback["model"] is None

    assert degraded["hypotheses"] == []
    assert degraded["hypothesis_details"] == []

    assert degraded["grounding"][
        "hypothesis_selection"
    ] == "unavailable"

    assert degraded["grounding"][
        "root_cause_confirmed"
    ] is False

    assert fallback["review_required"] is True
    assert fallback["actions_executed"] == []


def test_provider_rejects_fabricated_evidence(
    incident, selection, monkeypatch
):
    monkeypatch.setenv(
        "GEMINI_API_KEY", "test-key"
    )

    malicious_output = {
        "hypotheses": [
            {
                **selection,
                "evidence_ids": ["E999"],
            }
        ]
    }

    with patch("google.genai.Client") as mock_client:
        client = (
            mock_client.return_value
            .__enter__.return_value
        )

        generate = client.models.generate_content

        generate.return_value.text = json.dumps(
            malicious_output
        )

        with pytest.raises(HTTPException) as error:
            explain_with_gemini(incident, [])

        assert error.value.status_code == 502
        assert generate.call_count == 1


def test_invalid_model_output_triggers_fallback(
    incident, selection, monkeypatch
):
    monkeypatch.setenv(
        "GEMINI_API_KEY", "test-key"
    )

    malicious_output = {
        "hypotheses": [selection],
        "observations": [
            "CPU utilization is 95 percent"
        ],
    }

    with patch(
        "app.main.investigate",
        return_value=incident,
    ):
        with patch(
            "google.genai.Client"
        ) as mock_client:

            client = (
                mock_client.return_value
                .__enter__.return_value
            )

            client.models.generate_content.return_value.text = (
                json.dumps(malicious_output)
            )

            result = asyncio.run(explain(100.0))

    assert result["ai_status"] == "degraded"
    assert result["ai_generated"] is False

    assert result["explanation"]["hypotheses"] == []

    assert result["explanation"]["observations"] == (
        grounded_observations(build_evidence(incident))
    )

    assert result["actions_executed"] == []
