"""Reviewed runbook retrieval for ADK workflows."""

from app.rag_service import select_runbooks
from app.observability import emit_retrieval_metrics


def retrieve_context(incident: dict) -> dict:
    """Reuse existing retrieval and deterministic fallback."""

    runbooks, metadata = select_runbooks(incident)
    emit_retrieval_metrics(runbooks, metadata)

    return {
        "runbooks": runbooks,
        "retrieval": metadata,
    }
