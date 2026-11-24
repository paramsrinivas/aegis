"""Reviewed runbook retrieval for ADK workflows."""

from app.rag_service import select_runbooks


def retrieve_context(incident: dict) -> dict:
    """Reuse existing retrieval and deterministic fallback."""

    runbooks, metadata = select_runbooks(incident)

    return {
        "runbooks": runbooks,
        "retrieval": metadata,
    }
