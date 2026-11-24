"""Deterministic incident triage."""

from app.grounding import build_reasoning_context


def prepare_triage(incident: dict) -> dict:
    """Prepare evidence without modifying incident severity."""

    context = build_reasoning_context(incident, [])

    return {
        "severity": incident["severity"],
        "evidence": context["evidence"],
        "allowed_hypotheses": context["allowed_hypotheses"],
        "constraints": context["constraints"],
    }
