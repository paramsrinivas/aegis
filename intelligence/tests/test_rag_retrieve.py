
"""Unit tests for hybrid RAG retrieval."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from rag.retrieve import (
    embed_query,
    hybrid_retrieve,
    lexical_search,
    reciprocal_rank_fusion,
    semantic_search,
)


def document(document_id):
    return {
        "document_id": document_id,
        "title": document_id,
        "source_path": f"runbooks/{document_id}.md",
        "content": "Reviewed operational guidance.",
        "issue_tags": ["high_latency"],
    }


def test_rrf_combines_rankings():
    semantic = [document("a"), document("b")]
    lexical = [document("b"), document("c")]

    results = reciprocal_rank_fusion(semantic, lexical)

    assert results[0]["document_id"] == "b"
    assert results[0]["semantic_rank"] == 2
    assert results[0]["lexical_rank"] == 1
    assert results[0]["rrf_score"] == pytest.approx(
        1 / 62 + 1 / 61
    )


def test_rrf_deduplicates_documents():
    results = reciprocal_rank_fusion(
        [document("a")],
        [document("a")],
    )

    assert len(results) == 1
    assert results[0]["rrf_score"] == pytest.approx(2 / 61)


def test_rrf_handles_empty_results():
    assert reciprocal_rank_fusion([], []) == []


def test_rrf_handles_single_retrieval_method():
    results = reciprocal_rank_fusion(
        [document("a"), document("b")],
        [],
    )

    assert [d["document_id"] for d in results] == ["a", "b"]


def test_rrf_respects_result_limit():
    results = reciprocal_rank_fusion(
        [document("a"), document("b"), document("c")],
        [],
        limit=1,
    )

    assert len(results) == 1


def test_rrf_deterministic_tie_breaking():
    results = reciprocal_rank_fusion(
        [document("b")],
        [document("a")],
    )

    assert [d["document_id"] for d in results] == ["a", "b"]


def test_rrf_preserves_provenance():
    results = reciprocal_rank_fusion([document("a")], [])

    assert results[0]["source_path"] == "runbooks/a.md"
    assert results[0]["content"] == "Reviewed operational guidance."


def test_rrf_preserves_both_retrieval_scores():
    semantic = [{**document("a"), "semantic_score": 0.91}]
    lexical = [{**document("a"), "lexical_score": 0.08}]

    result = reciprocal_rank_fusion(semantic, lexical)[0]

    assert result["semantic_score"] == 0.91
    assert result["lexical_score"] == 0.08


def test_query_embedding_configuration():
    client = MagicMock()

    client.models.embed_content.return_value = SimpleNamespace(
        embeddings=[SimpleNamespace(values=[0.01] * 768)]
    )

    result = embed_query(client, "Backend latency increasing")

    assert len(result) == 768

    kwargs = client.models.embed_content.call_args.kwargs

    assert kwargs["model"] == "gemini-embedding-001"
    assert kwargs["config"].task_type == "RETRIEVAL_QUERY"
    assert kwargs["config"].output_dimensionality == 768


def test_empty_tags_prevent_retrieval():
    connection = MagicMock()
    client = MagicMock()

    assert hybrid_retrieve(connection, client, "latency", []) == []

    client.models.embed_content.assert_not_called()
    connection.cursor.assert_not_called()


def test_empty_query_prevents_retrieval():
    connection = MagicMock()
    client = MagicMock()

    assert hybrid_retrieve(
        connection, client, " ", ["high_latency"]
    ) == []

    client.models.embed_content.assert_not_called()


def test_semantic_search_uses_issue_tag_filter():
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = []

    semantic_search(
        connection,
        [0.01] * 768,
        ["high_latency"],
    )

    sql, parameters = cursor.execute.call_args.args

    assert "issue_tags &&" in sql
    assert parameters[1] == ["high_latency"]
    assert parameters[2] == "gemini-embedding-001"


def test_lexical_search_uses_issue_tag_filter():
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = []

    lexical_search(connection, "latency", ["high_latency"])

    sql, parameters = cursor.execute.call_args.args

    assert "issue_tags &&" in sql
    assert parameters[1] == ["high_latency"]

