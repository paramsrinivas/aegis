
"""Constrained incident reasoning and evidence validation."""

from app.evidence import validate_evidence_references


HYPOTHESIS_CATALOG = {
    "resource_contention": {
        "issues": {"high_latency"},
        "statement": "may be experiencing resource contention.",
        "check": "Inspect CPU, memory and queueing metrics.",
    },
    "increased_load": {
        "issues": {"high_latency"},
        "statement": "may be experiencing increased request volume.",
        "check": "Compare request volume against peer backends.",
    },
    "dependency_latency": {
        "issues": {"high_latency"},
        "statement": "may be affected by downstream dependency latency.",
        "check": "Inspect downstream dependency response times.",
    },
    "transient_degradation": {
        "issues": {"high_latency"},
        "statement": "may be experiencing transient performance degradation.",
        "check": "Compare repeated latency measurements over time.",
    },
    "application_failure": {
        "issues": {"unhealthy"},
        "statement": "may be experiencing an application failure.",
        "check": "Inspect application logs and health endpoint responses.",
    },
    "dependency_failure": {
        "issues": {"unhealthy"},
        "statement": "may be affected by a dependency failure.",
        "check": "Verify dependency connectivity and availability.",
    },
    "readiness_failure": {
        "issues": {"unhealthy"},
        "statement": "may have a readiness or startup problem.",
        "check": "Inspect container readiness and startup logs.",
    },
    "probe_failure": {
        "issues": {"unknown_latency"},
        "statement": "may be affected by a telemetry collection failure.",
        "check": "Inspect manager probe scheduling and timeout errors.",
    },
    "stale_telemetry": {
        "issues": {"unknown_latency"},
        "statement": "may have missing or stale telemetry.",
        "check": "Verify telemetry freshness and collection status.",
    },
}


def validate_hypotheses(
    hypotheses: list[dict],
    evidence: list[dict],
) -> list[dict]:
    """Validate selected hypotheses against observed incident types."""

    if not isinstance(hypotheses, list):
        raise ValueError("Hypotheses must be a list")

    if len(hypotheses) > 10:
        raise ValueError("Too many hypotheses")

    evidence_by_id = {
        item["id"]: item for item in evidence
    }

    validated = []
    seen = set()

    for item in hypotheses:
        if not isinstance(item, dict):
            raise ValueError("Invalid hypothesis")

        if set(item) != {
            "hypothesis_id",
            "backend",
            "evidence_ids",
        }:
            raise ValueError("Unexpected hypothesis fields")

        hypothesis_id = item["hypothesis_id"]
        backend = item["backend"]

        if not isinstance(hypothesis_id, str):
            raise ValueError("Invalid hypothesis ID")

        if not isinstance(backend, str) or not backend.strip():
            raise ValueError("Invalid backend")

        if hypothesis_id not in HYPOTHESIS_CATALOG:
            raise ValueError("Unknown hypothesis ID")

        references = validate_evidence_references(
            item["evidence_ids"],
            evidence,
        )

        definition = HYPOTHESIS_CATALOG[hypothesis_id]

        supporting_evidence = [
            evidence_by_id[ref] for ref in references
        ]

        for fact in supporting_evidence:
            if fact["backend"] != backend:
                raise ValueError("Evidence backend mismatch")

            if fact["kind"] not in {
                "health",
                "latency",
                "missing_latency",
                "finding",
            }:
                raise ValueError("Invalid supporting evidence type")

        matching_finding = any(
            fact["kind"] == "finding"
            and fact["value"] in definition["issues"]
            for fact in supporting_evidence
        )

        if not matching_finding:
            raise ValueError("Hypothesis has no relevant finding")

        identity = (hypothesis_id, backend)

        if identity in seen:
            raise ValueError("Duplicate hypothesis")

        seen.add(identity)

        validated.append({
            "hypothesis_id": hypothesis_id,
            "backend": backend,
            "evidence_ids": references,
            "statement": (
                f"{backend} {definition['statement']}"
            ),
            "recommended_check": (
                f"{backend}: {definition['check']}"
            ),
            "status": "unconfirmed",
        })

    return validated
