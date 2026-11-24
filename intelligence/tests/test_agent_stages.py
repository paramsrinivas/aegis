"""Tests for deterministic ADK diagnostic stages."""

from copy import deepcopy
from unittest.mock import patch

import pytest

from app.agents.triage import prepare_triage
from app.agents.retrieval import retrieve_context
from app.agents.validation import validate_selection


@pytest.fixture
def incident():
    return {
        "threshold_ms": 100.0,
        "severity": "medium",
        "backends": [
            {
                "name": "backend1",
                "healthy": True,
                "ewma_ms": 180.0,
            },
            {
                "name": "backend2",
                "healthy": True,
                "ewma_ms": 40.0,
            },
        ],
        "findings": [{
            "backend": "backend1",
            "issue": "high_latency",
            "evidence": "Backend latency exceeds threshold.",
        }],
        "limitations": [],
    }


def selection_for(incident):
    triage = prepare_triage(incident)

    candidate = next(
        item for item in triage["allowed_hypotheses"]
        if item["hypothesis_id"] == "resource_contention"
    )

    return {
        "hypotheses": [{
            "hypothesis_id": candidate["hypothesis_id"],
            "backend": candidate["backend"],
            "evidence_ids": [
                candidate["required_evidence_id"]
            ],
        }]
    }


def test_triage_preserves_incident(incident):
    original = deepcopy(incident)

    result = prepare_triage(incident)

    assert result["severity"] == "medium"
    assert result["evidence"]
    assert incident == original


def test_triage_limits_candidates(incident):
    result = prepare_triage(incident)

    assert len(result["allowed_hypotheses"]) == 4

    assert all(
        item["backend"] == "backend1"
        for item in result["allowed_hypotheses"]
    )


def test_retrieval_preserves_metadata(incident):
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

    with patch(
        "app.agents.retrieval.select_runbooks",
        return_value=(runbooks, metadata),
    ) as retrieve:
        result = retrieve_context(incident)

    retrieve.assert_called_once_with(incident)

    assert result["runbooks"] == runbooks
    assert result["retrieval"] == metadata


def test_retrieval_preserves_fallback(incident):
    metadata = {
        "mode": "deterministic_fallback",
        "fallback": True,
        "reason": "rag_unavailable",
    }

    with patch(
        "app.agents.retrieval.select_runbooks",
        return_value=([], metadata),
    ):
        result = retrieve_context(incident)

    assert result["retrieval"]["fallback"] is True


def test_valid_selection_is_grounded(incident):
    result = validate_selection(
        incident,
        selection_for(incident),
    )

    assert len(result["hypothesis_details"]) == 1

    assert result["grounding"][
        "evidence_references_validated"
    ] is True

    assert result["grounding"][
        "root_cause_confirmed"
    ] is False

    assert result["hypothesis_details"][0][
        "status"
    ] == "unconfirmed"


def test_reject_invented_evidence(incident):
    selection = selection_for(incident)

    selection["hypotheses"][0]["evidence_ids"] = [
        "E999"
    ]

    with pytest.raises(ValueError):
        validate_selection(incident, selection)


def test_reject_cross_backend_evidence(incident):
    selection = selection_for(incident)

    selection["hypotheses"][0]["backend"] = "backend2"

    with pytest.raises(ValueError):
        validate_selection(incident, selection)


def test_reject_unsupported_hypothesis(incident):
    selection = selection_for(incident)

    selection["hypotheses"][0][
        "hypothesis_id"
    ] = "application_failure"

    with pytest.raises(ValueError):
        validate_selection(incident, selection)


def test_reject_duplicate_hypotheses(incident):
    selection = selection_for(incident)

    selection["hypotheses"].append(
        deepcopy(selection["hypotheses"][0])
    )

    with pytest.raises(ValueError):
        validate_selection(incident, selection)


def test_empty_selection_retains_observations(incident):
    result = validate_selection(
        incident,
        {"hypotheses": []},
    )

    assert result["observations"]
    assert result["recommended_checks"]
    assert result["hypothesis_details"] == []
