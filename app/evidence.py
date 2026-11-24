
"""Deterministic evidence registry for incident explanations."""

from typing import Any


def build_evidence(incident: dict) -> list[dict]:
    """Convert validated incident telemetry into referenceable facts."""

    evidence: list[dict] = []

    def add(kind: str, value: Any, statement: str, backend=None):
        evidence.append({
            "id": f"E{len(evidence) + 1:03d}",
            "kind": kind,
            "backend": backend,
            "value": value,
            "statement": statement,
        })

    threshold = incident["threshold_ms"]

    add(
        "threshold",
        threshold,
        f"Configured latency threshold is {threshold} ms.",
    )

    for backend in sorted(
        incident["backends"],
        key=lambda item: item["name"],
    ):
        name = backend["name"]
        healthy = backend["healthy"]
        latency = backend["ewma_ms"]

        health_label = "healthy" if healthy else "unhealthy"

        add(
            "health",
            healthy,
            f"{name} is marked {health_label} by the manager.",
            backend=name,
        )

        if latency is None:
            add(
                "missing_latency",
                None,
                f"{name} has no available EWMA latency measurement.",
                backend=name,
            )
        else:
            add(
                "latency",
                latency,
                f"{name} EWMA latency is {latency:.2f} ms.",
                backend=name,
            )

    for finding in incident["findings"]:
        add(
            "finding",
            finding["issue"],
            finding["evidence"],
            backend=finding["backend"],
        )

    add(
        "severity",
        incident["severity"],
        f"Calculated severity is {incident['severity']}.",
    )

    for limitation in incident["limitations"]:
        add(
            "limitation",
            limitation,
            limitation,
        )

    return evidence


def validate_evidence_references(
    references: list[str],
    evidence: list[dict],
) -> list[str]:
    """Reject empty, duplicate or unknown evidence references."""

    if not isinstance(references, list) or not references:
        raise ValueError("Evidence references are required")

    if not all(isinstance(ref, str) for ref in references):
        raise ValueError("Evidence references must be strings")

    if len(references) != len(set(references)):
        raise ValueError("Duplicate evidence references")

    valid_ids = {item["id"] for item in evidence}

    for ref in references:
        if ref not in valid_ids:
            raise ValueError("Unknown evidence reference")

    return references


def grounded_observations(evidence: list[dict]) -> list[str]:
    """Generate factual observations without model-generated text."""

    observation_types = {
        "threshold",
        "health",
        "latency",
        "missing_latency",
        "finding",
        "severity",
    }

    return [
        f"[{item['id']}] {item['statement']}"
        for item in evidence
        if item["kind"] in observation_types
    ]

