
"""Live hybrid retrieval checks against reviewed Aegis runbooks."""

import os
import time

import psycopg
from google import genai

from rag.retrieve import hybrid_retrieve


CASES = [
    {
        "name": "Elevated latency",
        "query": "latency",
        "tags": ["high_latency"],
        "expected": {"runbook:latency"},
    },
    {
        "name": "Unhealthy backend",
        "query": "health endpoint",
        "tags": ["unhealthy"],
        "expected": {"runbook:unhealthy"},
    },
    {
        "name": "Missing telemetry",
        "query": "missing telemetry",
        "tags": ["unknown_latency"],
        "expected": {"runbook:missing-telemetry"},
    },
    {
        "name": "Cross-tag isolation",
        "query": "latency",
        "tags": ["unhealthy"],
        "expected": {"runbook:unhealthy"},
    },
    {
        "name": "Multi-issue incident",
        "query": "latency",
        "tags": ["high_latency", "unknown_latency"],
        "expected": {
            "runbook:latency",
            "runbook:missing-telemetry",
        },
    },
    {
        "name": "Unknown issue tag",
        "query": "backend failure",
        "tags": ["unsupported_issue"],
        "expected": set(),
    },
    {
        "name": "No issue tags",
        "query": "backend latency",
        "tags": [],
        "expected": set(),
    },
]


def main():
    client = genai.Client(
        api_key=os.environ["GEMINI_API_KEY"]
    )

    passed = 0
    timings = []

    with psycopg.connect(
        os.environ["AEGIS_VECTOR_DATABASE_URL"],
        autocommit=True,
    ) as connection:

        for case in CASES:
            start = time.perf_counter()

            results = hybrid_retrieve(
                connection,
                client,
                case["query"],
                case["tags"],
            )

            elapsed_ms = (time.perf_counter() - start) * 1000
            timings.append(elapsed_ms)

            actual = {
                document["document_id"]
                for document in results
            }

            assert actual == case["expected"], (
                f"{case['name']}: "
                f"expected {case['expected']}, got {actual}"
            )

            for document in results:
                assert set(document["issue_tags"]) & set(case["tags"])
                assert document["source_path"].startswith("runbooks/")
                assert document["content"]
                assert len(document["content_sha256"]) == 64
                assert document["rrf_score"] > 0

            scores = [
                document["rrf_score"]
                for document in results
            ]

            assert scores == sorted(scores, reverse=True)

            if case["name"] == "Elevated latency":
                assert results[0]["semantic_rank"] == 1
                assert results[0]["lexical_rank"] == 1

            if case["name"] == "Cross-tag isolation":
                assert results[0]["lexical_rank"] is None
                assert results[0]["semantic_rank"] == 1

            print(f"\nPASS: {case['name']}")
            print(f"  Query: {case['query']}")
            print(f"  Tags: {case['tags']}")
            print(f"  Retrieval time: {elapsed_ms:.2f} ms")

            for document in results:
                print(
                    f"  {document['document_id']} | "
                    f"semantic_rank={document['semantic_rank']} | "
                    f"lexical_rank={document['lexical_rank']} | "
                    f"rrf={document['rrf_score']:.6f}"
                )

            passed += 1

    print(f"\nLive retrieval checks: {passed}/{len(CASES)} passed")
    print(
        f"Mean retrieval time: "
        f"{sum(timings) / len(timings):.2f} ms"
    )


if __name__ == "__main__":
    main()

