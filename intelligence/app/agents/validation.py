"""Deterministic validation of ADK hypothesis selections."""

from app.agents.schemas import HypothesisOutput
from app.grounding import build_grounded_explanation


def validate_selection(
    incident: dict,
    selection: dict,
) -> dict:
    """Validate structure and supporting incident evidence."""

    parsed = HypothesisOutput.model_validate(selection)

    return build_grounded_explanation(
        incident,
        parsed.model_dump(),
    )
