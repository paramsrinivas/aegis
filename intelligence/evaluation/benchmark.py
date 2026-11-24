
"""Reproducible offline evaluation of Aegis AI grounding."""

import asyncio
import json
import time
from pathlib import Path
from unittest.mock import patch

from app.main import investigate, deterministic_fallback
from app.evidence import build_evidence, grounded_observations
from app.grounding import (
    build_reasoning_context,
    build_grounded_explanation,
)


SCENARIOS = [
    {
        "name": "healthy_infrastructure",
        "telemetry": {
            "backend1": {"healthy": 1, "ewma_ms": 45},
            "backend2": {"healthy": 1, "ewma_ms": 60},
        },
        "expected_severity": "none",
        "expected_issues": [],
    },
    {
        "name": "elevated_latency",
        "telemetry": {
            "backend1": {"healthy": 1, "ewma_ms": 45},
            "backend2": {"healthy": 1, "ewma_ms": 145},
        },
        "expected_severity": "medium",
        "expected_issues": ["high_latency"],
    },
    {
        "name": "single_backend_failure",
        "telemetry": {
            "backend1": {"healthy": 0, "ewma_ms": None},
            "backend2": {"healthy": 1, "ewma_ms": 50},
        },
        "expected_severity": "high",
        "expected_issues": ["unhealthy"],
    },
    {
        "name": "complete_backend_failure",
        "telemetry": {
            "backend1": {"healthy": 0, "ewma_ms": None},
            "backend2": {"healthy": 0, "ewma_ms": None},
        },
        "expected_severity": "critical",
        "expected_issues": ["unhealthy", "unhealthy"],
    },
    {
        "name": "missing_telemetry",
        "telemetry": {
            "backend1": {"healthy": 1, "ewma_ms": None},
        },
        "expected_severity": "unknown",
        "expected_issues": ["unknown_latency"],
    },
    {
        "name": "mixed_incident",
        "telemetry": {
            "backend1": {"healthy": 0, "ewma_ms": None},
            "backend2": {"healthy": 1, "ewma_ms": 180},
            "backend3": {"healthy": 1, "ewma_ms": None},
        },
        "expected_severity": "high",
        "expected_issues": [
            "unhealthy",
            "high_latency",
            "unknown_latency",
        ],
    },
    {
        "name": "threshold_boundary",
        "telemetry": {
            "backend1": {"healthy": 1, "ewma_ms": 100},
        },
        "expected_severity": "none",
        "expected_issues": [],
    },
    {
        "name": "multiple_slow_backends",
        "telemetry": {
            "backend1": {"healthy": 1, "ewma_ms": 130},
            "backend2": {"healthy": 1, "ewma_ms": 190},
        },
        "expected_severity": "medium",
        "expected_issues": [
            "high_latency",
            "high_latency",
        ],
    },
]


class MockResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


class MockClient:
    def __init__(self, payload):
        self.payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def get(self, url):
        return MockResponse(self.payload)


def evaluate_scenario(scenario):
    with patch(
        "app.main.httpx.AsyncClient",
        return_value=MockClient(scenario["telemetry"]),
    ):
        incident = asyncio.run(investigate(100.0))

    evidence = build_evidence(incident)

    context = build_reasoning_context(
        incident, []
    )

    candidates = context["allowed_hypotheses"]

    # Simulate valid model selections.
    # This does not evaluate live Gemini performance.
    selections = []
    seen_backends = set()

    for candidate in candidates:
        backend = candidate["backend"]

        if backend in seen_backends:
            continue

        seen_backends.add(backend)

        selections.append({
            "hypothesis_id": candidate["hypothesis_id"],
            "backend": backend,
            "evidence_ids": [
                candidate["required_evidence_id"]
            ],
        })

    model_output = {
        "hypotheses": selections
    }

    explanation = build_grounded_explanation(
        incident,
        model_output,
    )

    fallback = deterministic_fallback(incident)

    checks = {
        "severity_correct": (
            incident["severity"]
            == scenario["expected_severity"]
        ),
        "findings_correct": (
            sorted(
                item["issue"]
                for item in incident["findings"]
            )
            == sorted(scenario["expected_issues"])
        ),
        "evidence_consistent": (
            explanation["evidence"] == evidence
        ),
        "observations_consistent": (
            explanation["observations"]
            == grounded_observations(evidence)
        ),
        "hypotheses_unconfirmed": (
            all(
                item["status"] == "unconfirmed"
                for item in explanation["hypothesis_details"]
            )
            and explanation["grounding"][
                "root_cause_confirmed"
            ] is False
        ),
        "fallback_preserves_evidence": (
            fallback["evidence"] == evidence
            and fallback["observations"]
            == explanation["observations"]
        ),
        "fallback_has_no_hypotheses": (
            fallback["hypotheses"] == []
            and fallback["hypothesis_details"] == []
        ),
        "read_only_safety": (
            incident["actions_executed"] == []
        ),
    }

    return {
        "scenario": scenario["name"],
        "severity": incident["severity"],
        "checks": checks,
        "passed": all(checks.values()),
    }, incident


def evaluate_adversarial_outputs(incident):
    context = build_reasoning_context(
        incident, []
    )

    candidate = context["allowed_hypotheses"][0]

    valid = {
        "hypothesis_id": candidate["hypothesis_id"],
        "backend": candidate["backend"],
        "evidence_ids": [
            candidate["required_evidence_id"]
        ],
    }

    cases = {
        "fabricated_evidence": {
            "hypotheses": [
                {**valid, "evidence_ids": ["E999"]}
            ]
        },
        "invented_hypothesis": {
            "hypotheses": [
                {**valid, "hypothesis_id": "invented_cause"}
            ]
        },
        "wrong_backend": {
            "hypotheses": [
                {**valid, "backend": "backend99"}
            ]
        },
        "confirmed_root_cause": {
            "hypotheses": [
                {**valid, "status": "confirmed"}
            ]
        },
        "fabricated_cpu_metric": {
            "hypotheses": [valid],
            "observations": ["CPU utilization is 95%"],
        },
        "unauthorized_action": {
            "hypotheses": [valid],
            "actions_executed": ["Restarted backend2"],
        },
        "duplicate_hypothesis": {
            "hypotheses": [valid, valid]
        },
        "empty_evidence": {
            "hypotheses": [
                {**valid, "evidence_ids": []}
            ]
        },
        "malformed_output": {
            "hypotheses": "confirmed CPU failure"
        },
        "severity_override": {
            "hypotheses": [valid],
            "severity": "critical",
        },
    }

    results = []

    for name, output in cases.items():
        rejected = False

        try:
            build_grounded_explanation(
                incident, output
            )
        except ValueError:
            rejected = True

        results.append({
            "scenario": name,
            "rejected": rejected,
            "passed": rejected,
        })

    return results


def main():
    started = time.perf_counter()

    scenario_results = []
    latency_incident = None

    for scenario in SCENARIOS:
        result, incident = evaluate_scenario(
            scenario
        )

        scenario_results.append(result)

        if scenario["name"] == "elevated_latency":
            latency_incident = incident

        status = "PASS" if result["passed"] else "FAIL"

        print(f"{status}: {scenario['name']}")

    adversarial_results = (
        evaluate_adversarial_outputs(latency_incident)
    )

    print("\nADVERSARIAL EVALUATION")

    for result in adversarial_results:
        status = "PASS" if result["passed"] else "FAIL"

        print(f"{status}: {result['scenario']}")

    scenario_passed = sum(
        item["passed"]
        for item in scenario_results
    )

    adversarial_rejected = sum(
        item["rejected"]
        for item in adversarial_results
    )

    checks_total = sum(
        len(item["checks"])
        for item in scenario_results
    )

    checks_passed = sum(
        sum(item["checks"].values())
        for item in scenario_results
    )

    report = {
        "evaluation_type": "offline_controlled",
        "live_model_evaluated": False,
        "threshold_ms": 100.0,
        "metrics": {
            "incident_scenarios": len(scenario_results),
            "incident_scenarios_passed": scenario_passed,
            "diagnostic_checks": checks_total,
            "diagnostic_checks_passed": checks_passed,
            "adversarial_cases": len(adversarial_results),
            "adversarial_cases_rejected": adversarial_rejected,
            "adversarial_rejection_rate_pct": round(
                100 * adversarial_rejected
                / len(adversarial_results),
                2,
            ),
            "runtime_ms": round(
                (time.perf_counter() - started) * 1000,
                2,
            ),
        },
        "incident_results": scenario_results,
        "adversarial_results": adversarial_results,
        "limitations": [
            "Controlled synthetic telemetry.",
            "Simulated model outputs.",
            "Does not measure live Gemini accuracy.",
            "Does not establish confirmed root causes.",
            "Results apply only to evaluated scenarios.",
        ],
    }

    output_path = (
        Path(__file__).resolve().parent
        / "results.json"
    )

    output_path.write_text(
        json.dumps(report, indent=2) + "\n",
        encoding="utf-8",
    )

    print("\nEVALUATION SUMMARY")
    print(json.dumps(report["metrics"], indent=2))
    print(f"\nReport saved: {output_path}")

    if (
        scenario_passed != len(scenario_results)
        or adversarial_rejected != len(adversarial_results)
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
