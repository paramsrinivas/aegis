"""Live smoke checks for Aegis's selected semantic-coverage retrieval."""

import hashlib
import os
import time

import psycopg
from google import genai
from google.genai import types
from psycopg.rows import dict_row

from rag.documents import load_runbooks
from rag.retrieve import EMBEDDING_MODEL
from rag.validation import retrieve


CASES = [
    ("High latency", "backend elevated latency EWMA", ["high_latency"]),
    ("Unhealthy backend", "backend readiness and health failed", ["unhealthy"]),
    ("Unknown latency", "missing EWMA telemetry probe", ["unknown_latency"]),
    (
        "Mixed incident",
        "slow requests and failed backend health check",
        ["high_latency", "unhealthy"],
    ),
    (
        "Three-issue incident",
        "slow requests, failed readiness and stale telemetry",
        ["high_latency", "unhealthy", "unknown_latency"],
    ),
]


def validate_corpus(connection, documents):
    """Verify database rows against reviewed local source files."""

    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT document_id, source_path, title, content,
                   issue_tags, content_sha256, embedding_model,
                   vector_dims(embedding) AS dimensions
            FROM rag_documents
            """
        )
        rows = cursor.fetchall()

    stored = {row["document_id"]: row for row in rows}

    assert len(rows) == len(stored), "Duplicate stored IDs"
    assert set(stored) == set(documents), "Corpus ID mismatch"

    for document_id, doc in documents.items():
        row = stored[document_id]

        assert row["source_path"] == doc["source_path"]
        assert row["title"] == doc["title"]
        assert row["content"] == doc["content"]
        assert set(row["issue_tags"]) == set(doc["issue_tags"])
        assert row["content_sha256"] == doc["content_sha256"]
        assert hashlib.sha256(
            row["content"].encode("utf-8")
        ).hexdigest() == doc["content_sha256"]
        assert row["embedding_model"] == EMBEDDING_MODEL
        assert row["dimensions"] == 768


def main():
    documents = {
        doc["document_id"]: doc
        for doc in load_runbooks()
    }

    assert len(documents) == 12, (
        f"Expected the reviewed 12-document corpus; "
        f"found {len(documents)}"
    )

    durations = []

    with psycopg.connect(
        os.environ["AEGIS_VECTOR_DATABASE_URL"],
        connect_timeout=3,
        autocommit=True,
    ) as connection:
        validate_corpus(connection, documents)
        print("PASS: Reviewed corpus integrity (12 documents)")

        with genai.Client(
            api_key=os.environ["GEMINI_API_KEY"],
            http_options=types.HttpOptions(
                timeout=7000,
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        ) as client:
            for name, query, tags in CASES:
                started = time.perf_counter()

                results = retrieve(
                    connection,
                    client,
                    query,
                    tags,
                    strategy="semantic_coverage",
                    limit=3,
                )

                elapsed = (
                    time.perf_counter() - started
                ) * 1000
                durations.append(elapsed)

                assert 1 <= len(results) <= 3, name

                ids = [
                    row["document_id"]
                    for row in results
                ]

                assert len(ids) == len(set(ids)), name

                for row in results:
                    doc = documents[row["document_id"]]

                    assert set(row["issue_tags"]) & set(tags)
                    assert row["source_path"] == doc["source_path"]
                    assert row["content_sha256"] == doc["content_sha256"]

                covered = {
                    tag
                    for row in results
                    for tag in row["issue_tags"]
                    if tag in tags
                }

                assert covered == set(tags), (
                    f"{name}: covered {covered}, "
                    f"expected {set(tags)}"
                )

                print(
                    f"PASS: {name}; "
                    f"documents={len(results)}; "
                    f"coverage={len(covered)}/{len(tags)}; "
                    f"elapsed_ms={elapsed:.2f}"
                )

            for name, query, tags in [
                ("Unsupported issue", "backend failure", ["unsupported"]),
                ("No issue tags", "backend latency", []),
                ("Empty query", "", ["high_latency"]),
            ]:
                results = retrieve(
                    connection,
                    client,
                    query,
                    tags,
                    strategy="semantic_coverage",
                    limit=3,
                )

                assert results == [], name
                print(f"PASS: {name}")

    print("Live retrieval smoke checks: 9/9 PASS")
    print(
        "Positive-query mean wall-clock duration: "
        f"{sum(durations) / len(durations):.2f} ms"
    )


if __name__ == "__main__":
    main()
