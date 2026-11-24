
"""Idempotent ingestion of reviewed runbooks into PostgreSQL/pgvector."""

import argparse
import math
import os

import psycopg
from google import genai
from google.genai import types

from rag.documents import load_runbooks


EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_DIMENSIONS = 768


def validate_embedding(values):
    """Reject malformed embeddings before database writes."""
    if len(values) != EMBEDDING_DIMENSIONS:
        raise ValueError(
            f"Expected {EMBEDDING_DIMENSIONS} dimensions, got {len(values)}"
        )

    if not all(isinstance(value, (int, float)) and math.isfinite(value)
               for value in values):
        raise ValueError("Embedding contains invalid values")

    if not any(value != 0 for value in values):
        raise ValueError("Embedding must not be a zero vector")

    return [float(value) for value in values]


def embed_document(client, document):
    """Generate a document embedding using Gemini."""
    response = client.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=document["content"],
        config=types.EmbedContentConfig(
            task_type="RETRIEVAL_DOCUMENT",
            output_dimensionality=EMBEDDING_DIMENSIONS,
        ),
    )

    if not response.embeddings or not response.embeddings[0].values:
        raise ValueError("Embedding API returned no values")

    return validate_embedding(response.embeddings[0].values)


def ingest_documents(connection, client, documents):
    """Insert or update changed documents; skip unchanged documents."""
    results = {"inserted": 0, "updated": 0, "skipped": 0}

    for document in documents:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT content_sha256, embedding_model, embedding IS NOT NULL
                FROM rag_documents
                WHERE document_id = %s
                """,
                (document["document_id"],),
            )
            existing = cursor.fetchone()

        if (
            existing is not None
            and existing[0] == document["content_sha256"]
            and existing[1] == EMBEDDING_MODEL
            and existing[2]
        ):
            results["skipped"] += 1
            continue

        # Generate and validate the embedding before modifying the database.
        embedding = embed_document(client, document)
        vector_literal = "[" + ",".join(str(value) for value in embedding) + "]"

        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO rag_documents (
                        document_id,
                        source_path,
                        title,
                        content,
                        issue_tags,
                        content_sha256,
                        embedding_model,
                        embedding
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s::vector
                    )
                    ON CONFLICT (document_id)
                    DO UPDATE SET
                        source_path = EXCLUDED.source_path,
                        title = EXCLUDED.title,
                        content = EXCLUDED.content,
                        issue_tags = EXCLUDED.issue_tags,
                        content_sha256 = EXCLUDED.content_sha256,
                        embedding_model = EXCLUDED.embedding_model,
                        embedding = EXCLUDED.embedding,
                        updated_at = NOW()
                    """,
                    (
                        document["document_id"],
                        document["source_path"],
                        document["title"],
                        document["content"],
                        document["issue_tags"],
                        document["content_sha256"],
                        EMBEDDING_MODEL,
                        vector_literal,
                    ),
                )

        results["updated" if existing else "inserted"] += 1

    return results



def main():
    parser = argparse.ArgumentParser(
        description="Ingest reviewed Aegis runbooks into pgvector."
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv("AEGIS_VECTOR_DATABASE_URL"),
    )
    args = parser.parse_args()

    if not args.database_url:
        parser.error(
            "Provide --database-url or AEGIS_VECTOR_DATABASE_URL"
        )

    if not os.getenv("GEMINI_API_KEY"):
        parser.error("GEMINI_API_KEY is required")

    documents = load_runbooks()
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    with psycopg.connect(
        args.database_url,
        autocommit=True,
    ) as connection:
        results = ingest_documents(connection, client, documents)

    print(
        f"Inserted: {results['inserted']}, "
        f"Updated: {results['updated']}, "
        f"Skipped: {results['skipped']}"
    )


if __name__ == "__main__":
    main()

