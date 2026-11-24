"""Feature flag, document provenance and safe retrieval fallbacks."""
import pytest

from app import rag_service as service
from rag.documents import load_runbooks

FINDINGS = [{
    "backend": "backend2",
    "issue": "high_latency",
    "evidence": "EWMA 145 ms > 100 ms",
}]
INCIDENT = {"findings": FINDINGS}


def test_default_off_preserves_legacy(monkeypatch):
    monkeypatch.delenv("AEGIS_RAG_MODE", raising=False)
    monkeypatch.setattr(service, "retrieve_reviewed_runbooks", lambda _: pytest.fail("RAG must not be called"))
    runbooks, metadata = service.select_runbooks(INCIDENT)
    assert [r["id"] for r in runbooks] == ["latency"]
    assert metadata is None


def test_opt_in_success(monkeypatch):
    monkeypatch.setenv("AEGIS_RAG_MODE", "semantic_coverage")
    expected = [{"id": "resource-saturation", "title": "x", "content": "y", "source": "rag_runbooks/resource-saturation.md"}]
    monkeypatch.setattr(service, "retrieve_reviewed_runbooks", lambda _: expected)
    runbooks, metadata = service.select_runbooks(INCIDENT)
    assert runbooks is expected
    assert metadata == {"mode": "semantic_coverage", "fallback": False, "reason": None}


def test_rag_failure_uses_v1_runbooks(monkeypatch):
    monkeypatch.setenv("AEGIS_RAG_MODE", "semantic_coverage")
    def fail(_):
        raise RuntimeError("Simulated embedding provider outage")
    monkeypatch.setattr(service, "retrieve_reviewed_runbooks", fail)
    runbooks, metadata = service.select_runbooks(INCIDENT)
    assert [r["id"] for r in runbooks] == ["latency"]
    assert metadata["fallback"] is True
    assert metadata["reason"] == "rag_unavailable"


def test_invalid_mode_fails_to_deterministic(monkeypatch):
    monkeypatch.setenv("AEGIS_RAG_MODE", "unsafe")
    monkeypatch.setattr(service, "retrieve_reviewed_runbooks", lambda _: pytest.fail("RAG must not be called"))
    runbooks, metadata = service.select_runbooks(INCIDENT)
    assert [r["id"] for r in runbooks] == ["latency"]
    assert metadata["reason"] == "invalid_rag_mode"


def test_unsupported_tags_do_not_call_rag(monkeypatch):
    monkeypatch.setenv("AEGIS_RAG_MODE", "semantic_coverage")
    monkeypatch.setattr(service, "retrieve_reviewed_runbooks", lambda _: pytest.fail("RAG must not be called"))
    runbooks, metadata = service.select_runbooks({"findings": [{"issue": "unsupported"}]})
    assert runbooks == []
    assert metadata["reason"] == "no_eligible_tags"


def test_query_uses_only_recognized_tags_and_bounded_evidence():
    query, tags = service._query_and_tags([
        *FINDINGS,
        {"issue": "unhealthy", "evidence": "Health check failed"},
        {"issue": "completely_other", "evidence": "ignore this"},
    ])
    assert tags == ["high_latency", "unhealthy"]
    assert "Health check failed" in query
    assert "ignore this" not in query
    assert len(query) <= 2400


def test_reviewed_document_is_accepted():
    doc = next(d for d in load_runbooks() if d["document_id"] == "runbook:latency")
    converted = service._validate_and_convert([doc], ["high_latency"])
    assert converted == [{
        "id": "latency",
        "title": doc["title"],
        "content": doc["content"],
        "source": "runbooks/latency.md",
    }]


@pytest.mark.parametrize("field,value", [
    ("content_sha256", "0" * 64),
    ("source_path", "unexpected/latency.md"),
    ("title", "Unreviewed change"),
    ("content", "Tampered content"),
    ("issue_tags", ["unhealthy"]),
    ("document_id", "runbook:unknown"),
])
def test_tampered_or_unknown_document_fails_closed(field, value):
    doc = next(d for d in load_runbooks() if d["document_id"] == "runbook:latency")
    altered = {**doc, field: value}
    with pytest.raises(ValueError):
        service._validate_and_convert([altered], ["high_latency"])


def test_cross_issue_document_rejected():
    doc = next(d for d in load_runbooks() if d["document_id"] == "runbook:latency")
    with pytest.raises(ValueError):
        service._validate_and_convert([doc], ["unhealthy"])


def test_duplicate_document_rejected():
    doc = next(d for d in load_runbooks() if d["document_id"] == "runbook:latency")
    with pytest.raises(ValueError):
        service._validate_and_convert([doc, doc], ["high_latency"])


def test_empty_rag_results_fallback(monkeypatch):
    monkeypatch.setenv("AEGIS_RAG_MODE", "semantic_coverage")
    monkeypatch.setattr(service, "retrieve_reviewed_runbooks", lambda _: [])
    runbooks, metadata = service.select_runbooks(INCIDENT)
    assert [r["id"] for r in runbooks] == ["latency"]
    assert metadata["fallback"] is True


def test_password_is_encoded(monkeypatch):
    monkeypatch.delenv("AEGIS_VECTOR_DATABASE_URL", raising=False)
    monkeypatch.setenv("AEGIS_VECTOR_DB_PASSWORD", "has@colon:slash/")
    assert "has%40colon%3Aslash%2F" in service._database_url()


def test_explicit_database_url(monkeypatch):
    monkeypatch.setenv("AEGIS_VECTOR_DATABASE_URL", "postgresql://customhost/testdb")
    assert service._database_url() == "postgresql://customhost/testdb"
