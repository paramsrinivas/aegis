import pytest

from rag.optimized import (
    weighted_rrf,
    select_with_coverage,
    relaxed_lexical_search,
)


def doc(name, tag):
    return {
        "document_id": name,
        "issue_tags": [tag],
    }


A = doc("a", "high_latency")
B = doc("b", "high_latency")
C = doc("c", "unhealthy")
D = doc("d", "unknown_latency")


def test_weighted_fusion_prefers_semantic():
    results = weighted_rrf(
        [A, B],
        [B, A],
        semantic_weight=1,
        lexical_weight=0.25,
    )
    assert results[0]["document_id"] == "a"


def test_empty_lexical_preserves_semantic():
    results = weighted_rrf([A, B, C], [])
    assert [r["document_id"] for r in results] == [
        "a", "b", "c"
    ]


def test_zero_lexical_weight():
    results = weighted_rrf(
        [A], [B], lexical_weight=0
    )
    assert len(results) == 1
    assert results[0]["document_id"] == "a"


def test_duplicate_documents_not_double_counted():
    results = weighted_rrf([A, A], [])
    assert len(results) == 1
    assert results[0]["rrf_score"] == pytest.approx(
        1 / 61
    )


def test_empty_rankings():
    assert weighted_rrf([], []) == []


@pytest.mark.parametrize(
    "weights",
    [(-1, 1), (0, 0), (float("nan"), 1)],
)
def test_invalid_weights(weights):
    with pytest.raises(ValueError):
        weighted_rrf(
            [A], [B],
            semantic_weight=weights[0],
            lexical_weight=weights[1],
        )


def test_multi_issue_coverage():
    results = select_with_coverage(
        [A, B, C, D],
        ["high_latency", "unhealthy", "unknown_latency"],
        limit=3,
    )
    assert [r["document_id"] for r in results] == [
        "a", "c", "d"
    ]


def test_single_issue_preserves_ranking():
    results = select_with_coverage(
        [A, B],
        ["high_latency"],
        limit=2,
    )
    assert results == [A, B]


def test_coverage_rejects_unrelated_tags():
    results = select_with_coverage(
        [A, B, C],
        ["unhealthy"],
        limit=3,
    )
    assert results == [C]


def test_coverage_respects_limit():
    results = select_with_coverage(
        [A, B, C, D],
        ["high_latency", "unhealthy", "unknown_latency"],
        limit=2,
    )
    assert results == [A, C]


def test_coverage_without_candidates():
    assert select_with_coverage(
        [], ["unhealthy"]
    ) == []


def test_no_tags_returns_empty():
    assert select_with_coverage([A], []) == []


def test_lexical_empty_query():
    assert relaxed_lexical_search(
        None, "", ["high_latency"]
    ) == []


def test_lexical_no_tags():
    assert relaxed_lexical_search(
        None, "backend latency", []
    ) == []
