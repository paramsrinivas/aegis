
"""Real PostgreSQL integration checks using synthetic embeddings."""

import os
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import psycopg

from rag.documents import load_runbooks
from rag.ingest import ingest_documents, EMBEDDING_DIMENSIONS


def main():
    client = MagicMock()

    client.models.embed_content.return_value = SimpleNamespace(
        embeddings=[
            SimpleNamespace(values=[0.01] * EMBEDDING_DIMENSIONS)
        ]
    )

    document = dict(load_runbooks()[0])

    # Isolate synthetic test data from real runbooks.
    test_id = f"integration-test:{uuid4().hex}"
    document["document_id"] = test_id
    document["source_path"] = f"integration-tests/{test_id}.md"

    with psycopg.connect(
        os.environ["AEGIS_VECTOR_DATABASE_URL"],
        autocommit=True,
    ) as connection:
        try:
            # 1. Verify real insertion.
            result = ingest_documents(connection, client, [document])

            assert result == {
                "inserted": 1,
                "updated": 0,
                "skipped": 0,
            }
            print("PASS: PostgreSQL insertion")

            # 2. Verify stored vector dimensions.
            row = connection.execute(
                """
                SELECT vector_dims(embedding)
                FROM rag_documents
                WHERE document_id = %s
                """,
                (test_id,),
            ).fetchone()

            assert row == (768,)
            print("PASS: Stored vector has 768 dimensions")

            # 3. Verify idempotency.
            client.reset_mock()

            result = ingest_documents(connection, client, [document])

            assert result == {
                "inserted": 0,
                "updated": 0,
                "skipped": 1,
            }

            client.models.embed_content.assert_not_called()
            print("PASS: Unchanged document skipped")

            # 4. Verify changed document update.
            import hashlib

            document["content"] += "\nIntegration test update."
            document["content_sha256"] = hashlib.sha256(
                document["content"].encode("utf-8")
            ).hexdigest()

            result = ingest_documents(connection, client, [document])

            assert result == {
                "inserted": 0,
                "updated": 1,
                "skipped": 0,
            }
            print("PASS: Changed document updated")

            # 5. Verify failure preserves the stored document.
            stored_before = connection.execute(
                """
                SELECT content, content_sha256, embedding::text
                FROM rag_documents
                WHERE document_id = %s
                """,
                (test_id,),
            ).fetchone()

            document["content"] += "\nFailed update."
            document["content_sha256"] = hashlib.sha256(
                document["content"].encode("utf-8")
            ).hexdigest()

            client.models.embed_content.side_effect = RuntimeError(
                "Simulated embedding failure"
            )

            try:
                ingest_documents(connection, client, [document])
            except RuntimeError:
                pass
            else:
                raise AssertionError("Expected embedding failure")

            stored_after = connection.execute(
                """
                SELECT content, content_sha256, embedding::text
                FROM rag_documents
                WHERE document_id = %s
                """,
                (test_id,),
            ).fetchone()

            assert stored_before == stored_after
            print("PASS: Embedding failure preserves existing data")

        finally:
            connection.execute(
                "DELETE FROM rag_documents WHERE document_id = %s",
                (test_id,),
            )

            print("PASS: Synthetic test document cleaned up")

    print("\nAll 5 PostgreSQL integration checks passed.")


if __name__ == "__main__":
    main()

