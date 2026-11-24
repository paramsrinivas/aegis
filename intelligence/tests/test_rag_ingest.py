
"""Unit tests for RAG embedding validation and ingestion."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from rag.ingest import (
    EMBEDDING_DIMENSIONS,
    EMBEDDING_MODEL,
    embed_document,
    ingest_documents,
    validate_embedding,
)


def sample_document():
    return {
        "document_id": "runbook:latency",
        "source_path": "runbooks/latency.md",
        "title": "Elevated backend latency",
        "content": "# Elevated backend latency\nTags: high_latency\nCheck EWMA.",
        "issue_tags": ["high_latency"],
        "content_sha256": "a" * 64,
    }


def sample_embedding():
    return [0.01] * EMBEDDING_DIMENSIONS


def make_client(values=None):
    client = MagicMock()
    client.models.embed_content.return_value = SimpleNamespace(
        embeddings=[
            SimpleNamespace(
                values=sample_embedding() if values is None else values
            )
        ]
    )
    return client


def make_connection(existing=None):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = existing
    return connection, cursor


def test_valid_embedding():
    assert len(validate_embedding(sample_embedding())) == 768


@pytest.mark.parametrize(
    "values",
    [
        [0.1] * 767,
        [0.0] * 768,
        [float("nan")] * 768,
        [float("inf")] * 768,
    ],
)
def test_invalid_embedding_rejected(values):
    with pytest.raises(ValueError):
        validate_embedding(values)


def test_embedding_request_configuration():
    client = make_client()

    result = embed_document(client, sample_document())

    assert len(result) == 768

    kwargs = client.models.embed_content.call_args.kwargs
    assert kwargs["model"] == EMBEDDING_MODEL
    assert kwargs["contents"] == sample_document()["content"]
    assert kwargs["config"].task_type == "RETRIEVAL_DOCUMENT"
    assert kwargs["config"].output_dimensionality == 768


def test_unchanged_document_skips_embedding():
    document = sample_document()
    connection, cursor = make_connection(
        existing=(document["content_sha256"], EMBEDDING_MODEL, True)
    )
    client = make_client()

    result = ingest_documents(connection, client, [document])

    assert result == {"inserted": 0, "updated": 0, "skipped": 1}
    client.models.embed_content.assert_not_called()
    assert cursor.execute.call_count == 1


def test_new_document_inserted():
    connection, cursor = make_connection(existing=None)
    client = make_client()

    result = ingest_documents(
        connection, client, [sample_document()]
    )

    assert result == {"inserted": 1, "updated": 0, "skipped": 0}
    assert cursor.execute.call_count == 2
    assert connection.transaction.called


def test_changed_document_updated():
    connection, cursor = make_connection(
        existing=("b" * 64, EMBEDDING_MODEL, True)
    )
    client = make_client()

    result = ingest_documents(
        connection, client, [sample_document()]
    )

    assert result == {"inserted": 0, "updated": 1, "skipped": 0}
    client.models.embed_content.assert_called_once()


def test_embedding_failure_prevents_upsert():
    connection, cursor = make_connection(existing=None)
    client = make_client()
    client.models.embed_content.side_effect = RuntimeError(
        "Embedding service unavailable"
    )

    with pytest.raises(RuntimeError):
        ingest_documents(
            connection, client, [sample_document()]
        )

    assert cursor.execute.call_count == 1
    connection.transaction.assert_not_called()

