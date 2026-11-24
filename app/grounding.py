
"""Evidence-grounded incident explanation generation."""

from app.evidence import build_evidence, grounded_observations
from app.reasoning import (
    HYPOTHESIS_CATALOG,
    validate_hypotheses,
)


def build_reasoning_context(
    incident: dict,
    runbooks: list[dict],
) -> dict:
    """Construct the permitted reasoning context for Gemini."""

    evidence = build_evidence(incident)

    candidates = []

    for fact in evidence:
        if fact["kind"] != "finding":
            continue

        for hypothesis_id, definition in HYPOTHESIS_CATALOG.items():
            if fact["value"] not in definition["issues"]:
                continue

            candidates.append({
                "hypothesis_id": hypothesis_id,
                "backend": fact["backend"],
                "required_evidence_id": fact["id"],
                "description": definition["statement"],
                "recommended_check": definition["check"],
            })

    return {
        "evidence": evidence,
        "allowed_hypotheses": candidates,
        "runbooks": runbooks,
        "constraints": [
            "Select only allowed hypotheses.",
            "Use evidence from the same backend.",
            "Include the relevant finding evidence ID.",
            "Do not generate factual observations.",
            "Do not claim a confirmed root cause.",
            "Return an empty hypothesis list if appropriate.",
        ],
    }


def build_grounded_explanation(
    incident: dict,
    model_output: dict,
) -> dict:
    """Validate model selections and render trusted output."""

    if not isinstance(model_output, dict):
        raise ValueError("Model output must be an object")

    if set(model_output) != {"hypotheses"}:
        raise ValueError("Unexpected model output fields")

    evidence = build_evidence(incident)

    hypotheses = validate_hypotheses(
        model_output["hypotheses"],
        evidence,
    )

    checks = [
        item["recommended_check"]
        for item in hypotheses
    ]

    # Preserve basic diagnostic checks even when the
    # model does not select a hypothesis.
    for finding in incident["findings"]:
        backend = finding["backend"]
        issue = finding["issue"]

        if issue == "high_latency":
            checks.append(
                f"{backend}: Compare repeated latency measurements."
            )

        elif issue == "unhealthy":
            checks.append(
                f"{backend}: Inspect health endpoint responses."
            )

        elif issue == "unknown_latency":
            checks.append(
                f"{backend}: Verify telemetry availability."
            )

    if not checks:
        checks.append(
            "Continue monitoring backend health and latency."
        )

    return {
        "summary": (
            f"Detected {len(incident['findings'])} finding(s). "
            f"Incident severity: {incident['severity']}."
        ),
        "observations": grounded_observations(evidence),
        "hypotheses": [
            item["statement"] for item in hypotheses
        ],
        "recommended_checks": list(dict.fromkeys(checks)),
        "uncertainty": (
            "Root cause is unknown. "
            "Hypotheses are unconfirmed possibilities, "
            "not established causes. "
            "A single telemetry snapshot does not "
            "establish persistence or causality."
        ),
        "evidence": evidence,
        "hypothesis_details": hypotheses,
        "grounding": {
            "observations": "deterministic",
            "hypothesis_selection": "model",
            "hypothesis_wording": "catalogue",
            "evidence_references_validated": True,
            "root_cause_confirmed": False,
        },
    }
