from app.knowledge import retrieve
from app import ai
import pytest
from fastapi import HTTPException

def test_retrieval_matches_issue():
    hits = retrieve([{'issue': 'high_latency', 'evidence': 'EWMA 120 ms'}])
    assert hits and hits[0]['id'] == 'latency'
    assert hits[0]['source'] == 'runbooks/latency.md'

def test_empty_findings_return_no_runbooks():
    assert retrieve([]) == []

def test_missing_key_fails_closed(monkeypatch):
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    with pytest.raises(HTTPException) as err:
        ai.explain_with_gemini({}, [])
    assert err.value.status_code == 503
