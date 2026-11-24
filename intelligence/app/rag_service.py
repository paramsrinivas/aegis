"""Optional, fail-safe RAG retrieval for the incident explanation endpoint.

This module does not write telemetry, choose hypotheses, or execute remediations.
The existing deterministic runbooks remain the default and last-resort fallback.
"""

import hashlib
import logging
import os
from urllib.parse import quote

logger = logging.getLogger(__name__)

ISSUE_QUERIES = {
    "high_latency": "backend elevated latency EWMA slow request processing",
    "unhealthy": "unhealthy backend health endpoint readiness connectivity",
    "unknown_latency": "missing telemetry unavailable EWMA probe timeout stale measurements",
}


def _database_url():
    """Allow an explicit DSN, otherwise use the profile-gated local pgvector DB."""
    explicit = os.getenv("AEGIS_VECTOR_DATABASE_URL", "").strip()
    if explicit:
        return explicit
    password = quote(os.getenv("AEGIS_VECTOR_DB_PASSWORD", "aegis_local_dev"), safe="")
    return (
        "postgresql://aegis_rag:"
        f"{password}@vector-db:5432/aegis_rag"
    )


def _query_and_tags(findings):
    tags = sorted({
        finding.get("issue")
        for finding in findings[:30]
        if isinstance(finding, dict)
        and isinstance(finding.get("issue"), str)
        and finding.get("issue") in ISSUE_QUERIES
    })
    if not tags:
        return "", []
    phrases = [ISSUE_QUERIES[tag] for tag in tags]
    for finding in findings[:30]:
        if isinstance(finding, dict) and finding.get("issue") in tags:
            evidence = finding.get("evidence", "")
            if isinstance(evidence, str):
                phrases.append(evidence[:250])
    return " ".join(phrases)[:2400], tags


def _validate_and_convert(rows, tags):
    """Fail closed if pgvector returned data differs from reviewed local files."""
    from rag.documents import load_runbooks

    reviewed = {doc["document_id"]: doc for doc in load_runbooks()}
    result = []
    seen = set()
    for row in rows:
        document_id = row["document_id"]
        doc = reviewed.get(document_id)
        if doc is None or document_id in seen:
            raise ValueError("Unknown or duplicate RAG document")
        seen.add(document_id)
        if (
            row["source_path"] != doc["source_path"]
            or row["title"] != doc["title"]
            or row["content"] != doc["content"]
            or set(row["issue_tags"]) != set(doc["issue_tags"])
            or row["content_sha256"] != doc["content_sha256"]
            or hashlib.sha256(row["content"].encode("utf-8")).hexdigest()
                != doc["content_sha256"]
            or not set(tags).intersection(doc["issue_tags"])
        ):
            raise ValueError("RAG document failed reviewed-corpus validation")
        result.append({
            "id": document_id.removeprefix("runbook:"),
            "title": doc["title"],
            "content": doc["content"],
            "source": doc["source_path"],
        })
    return result


def retrieve_reviewed_runbooks(incident):
    """Retrieve top three reviewed runbooks using semantic rank + tag coverage."""
    from google import genai
    from google.genai import types
    import psycopg
    from rag.validation import retrieve

    query, tags = _query_and_tags(incident.get("findings", []))
    if not tags:
        return []
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("Embedding API not configured")

    with psycopg.connect(_database_url(), connect_timeout=3, autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SET statement_timeout = '3000ms'")
        with genai.Client(
            api_key=key,
            http_options=types.HttpOptions(
                timeout=7000,
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        ) as client:
            rows = retrieve(
                connection, client, query, tags,
                strategy="semantic_coverage", limit=3,
            )

    if not rows:
        raise ValueError("No relevant reviewed RAG runbooks returned")
    return _validate_and_convert(rows, tags)


def select_runbooks(incident):
    """Select default or opt-in retrieval; return (runbooks, metadata).

    When disabled, exactly the legacy runbook objects and no metadata are used.
    When enabled, no retrieval exception can prevent a grounded explanation.
    """
    from app.knowledge import retrieve as deterministic_retrieve

    mode = os.getenv("AEGIS_RAG_MODE", "off").strip().lower()
    if mode == "off":
        return deterministic_retrieve(incident["findings"]), None

    if mode != "semantic_coverage":
        logger.warning("Unsupported RAG mode; using deterministic runbooks")
        return deterministic_retrieve(incident["findings"]), {
            "mode": "deterministic_fallback",
            "fallback": True,
            "reason": "invalid_rag_mode",
        }

    query, tags = _query_and_tags(incident["findings"])
    if not tags:
        return deterministic_retrieve(incident["findings"]), {
            "mode": "semantic_coverage",
            "fallback": False,
            "reason": "no_eligible_tags",
        }

    try:
        runbooks = retrieve_reviewed_runbooks(incident)
        if not runbooks:
            raise ValueError("No reviewed runbooks available")
        return runbooks, {
            "mode": "semantic_coverage",
            "fallback": False,
            "reason": None,
        }
    except Exception as exc:
        # Never log exception messages: a DSN or provider error may contain secrets.
        logger.warning("RAG retrieval unavailable: error_type=%s", type(exc).__name__)
        return deterministic_retrieve(incident["findings"]), {
            "mode": "deterministic_fallback",
            "fallback": True,
            "reason": "rag_unavailable",
        }
