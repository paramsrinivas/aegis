"""Tests for restricted ADK agent configuration."""

import pytest

from pydantic import ValidationError

from app.agents.schemas import HypothesisOutput
from app.agents.hypothesis import build_hypothesis_agent


def test_empty_hypothesis_selection():
    result = HypothesisOutput.model_validate({
        "hypotheses": [],
    })

    assert result.model_dump() == {"hypotheses": []}


def test_valid_hypothesis_selection():
    result = HypothesisOutput.model_validate({
        "hypotheses": [{
            "hypothesis_id": "resource_contention",
            "backend": "backend1",
            "evidence_ids": ["E004"],
        }],
    })

    assert len(result.hypotheses) == 1


def test_reject_extra_output_fields():
    with pytest.raises(ValidationError):
        HypothesisOutput.model_validate({
            "hypotheses": [],
            "actions": ["restart backend1"],
        })


def test_reject_extra_hypothesis_fields():
    with pytest.raises(ValidationError):
        HypothesisOutput.model_validate({
            "hypotheses": [{
                "hypothesis_id": "resource_contention",
                "backend": "backend1",
                "evidence_ids": ["E004"],
                "root_cause_confirmed": True,
            }],
        })


def test_reject_empty_evidence():
    with pytest.raises(ValidationError):
        HypothesisOutput.model_validate({
            "hypotheses": [{
                "hypothesis_id": "resource_contention",
                "backend": "backend1",
                "evidence_ids": [],
            }],
        })


def test_reject_excessive_hypotheses():
    item = {
        "hypothesis_id": "resource_contention",
        "backend": "backend1",
        "evidence_ids": ["E004"],
    }

    with pytest.raises(ValidationError):
        HypothesisOutput.model_validate({
            "hypotheses": [item] * 11,
        })


def test_reject_non_string_evidence():
    with pytest.raises(ValidationError):
        HypothesisOutput.model_validate({
            "hypotheses": [{
                "hypothesis_id": "resource_contention",
                "backend": "backend1",
                "evidence_ids": [123],
            }],
        })


def test_agent_restrictions():
    agent = build_hypothesis_agent()

    assert agent.name == "hypothesis_agent"
    assert agent.tools == []
    assert agent.sub_agents == []
    assert agent.code_executor is None
    assert agent.disallow_transfer_to_parent
    assert agent.disallow_transfer_to_peers
    from app.agents.schemas import GeminiHypothesisOutput

    assert agent.output_schema is GeminiHypothesisOutput
    assert agent.output_key == "hypothesis_output"
    assert agent.timeout == 20.0
