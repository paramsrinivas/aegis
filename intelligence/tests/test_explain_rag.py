"""Contract tests for disabled, enabled and degraded /explain retrieval."""
import asyncio
from unittest.mock import patch

from app.main import explain

INCIDENT = {
    "severity": "medium",
    "threshold_ms": 100.0,
    "backends": [{"name": "backend2", "healthy": True, "ewma_ms": 145.0}],
    "findings": [{
        "backend": "backend2", "issue": "high_latency",
        "evidence": "EWMA 145 ms > 100 ms",
    }],
    "source": "Aegis manager /weights",
    "limitations": ["Single telemetry snapshot"],
    "actions_executed": [],
}

EXPLANATION = {
    "summary": "Test explanation",
    "hypotheses": [],
    "observations": [],
    "recommended_checks": [],
    "uncertainty": "Root cause unknown",
}


def call_explain():
    with patch("app.main.investigate", return_value=INCIDENT), patch(
        "app.ai.explain_with_gemini", return_value=EXPLANATION
    ) as generate:
        response = asyncio.run(explain(100.0))
    return response, generate


def test_default_response_contract_unchanged(monkeypatch):
    monkeypatch.delenv("AEGIS_RAG_MODE", raising=False)
    with patch("app.rag_service.retrieve_reviewed_runbooks") as rag:
        response, generate = call_explain()
    rag.assert_not_called()
    assert "retrieval" not in response
    assert [r["id"] for r in response["runbooks"]] == ["latency"]
    assert response["review_required"] is True
    assert response["actions_executed"] == []
    generate.assert_called_once()
    assert generate.call_args.args[1][0]["id"] == "latency"


def test_enabled_passes_rag_content_to_existing_grounding(monkeypatch):
    monkeypatch.setenv("AEGIS_RAG_MODE", "semantic_coverage")
    rag_doc = {
        "id": "resource-saturation", "title": "Resource saturation",
        "source": "rag_runbooks/resource-saturation.md", "content": "# Reviewed operational guidance",
    }
    with patch("app.rag_service.retrieve_reviewed_runbooks", return_value=[rag_doc]):
        response, generate = call_explain()
    assert response["retrieval"] == {
        "mode": "semantic_coverage", "fallback": False, "reason": None,
    }
    assert response["runbooks"][0]["source"] == rag_doc["source"]
    assert generate.call_args.args[1] == [rag_doc]
    assert response["review_required"] is True
    assert response["actions_executed"] == []


def test_rag_failure_keeps_gemini_available(monkeypatch):
    monkeypatch.setenv("AEGIS_RAG_MODE", "semantic_coverage")
    with patch(
        "app.rag_service.retrieve_reviewed_runbooks",
        side_effect=ConnectionError("Simulated database outage"),
    ):
        response, generate = call_explain()
    assert response["retrieval"]["mode"] == "deterministic_fallback"
    assert response["retrieval"]["fallback"] is True
    assert response["ai_generated"] is True
    assert [r["id"] for r in response["runbooks"]] == ["latency"]
    assert generate.call_args.args[1][0]["source"] == "runbooks/latency.md"


def test_no_findings_are_not_sent_to_rag(monkeypatch):
    monkeypatch.setenv("AEGIS_RAG_MODE", "semantic_coverage")
    with patch("app.main.investigate", return_value={**INCIDENT,"findings": []}), patch(
        "app.ai.explain_with_gemini", return_value=EXPLANATION
    ) as generate, patch("app.rag_service.retrieve_reviewed_runbooks") as rag:
        response = asyncio.run(explain(100.0))
    rag.assert_not_called()
    assert response["runbooks"] == []
    assert response["retrieval"]["reason"] == "no_eligible_tags"
    generate.assert_called_once()
