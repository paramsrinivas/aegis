"""Experimental retrieval with relaxed FTS and weighted RRF."""

import math

from psycopg.rows import dict_row

from rag.retrieve import (
    CANDIDATE_LIMIT,
    embed_query,
    semantic_search,
)


def relaxed_lexical_search(
    connection,
    query,
    issue_tags,
    limit=CANDIDATE_LIMIT,
):
    if limit <= 0:
        raise ValueError("limit must be positive")

    if not query.strip() or not issue_tags:
        return []

    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            WITH terms AS (
                SELECT array_to_string(
                    ARRAY(
                        SELECT quote_literal(term)
                        FROM unnest(
                            tsvector_to_array(
                                to_tsvector('english', %s)
                            )
                        ) AS term
                    ),
                    ' | '
                )::tsquery AS query
            )
            SELECT
                document_id,
                source_path,
                title,
                content,
                issue_tags,
                content_sha256,
                ts_rank(search_vector, terms.query)
                    AS lexical_score
            FROM rag_documents
            CROSS JOIN terms
            WHERE issue_tags && %s::text[]
              AND search_vector @@ terms.query
            ORDER BY lexical_score DESC, document_id
            LIMIT %s
            """,
            (query, sorted(set(issue_tags)), limit),
        )

        return cursor.fetchall()


def weighted_rrf(
    semantic_results,
    lexical_results,
    semantic_weight=1.0,
    lexical_weight=0.25,
    k=60,
    limit=10,
):
    if k <= 0 or limit <= 0:
        raise ValueError("k and limit must be positive")

    weights = (semantic_weight, lexical_weight)

    if (
        any(not math.isfinite(w) or w < 0 for w in weights)
        or sum(weights) <= 0
    ):
        raise ValueError("Invalid fusion weights")

    fused = {}

    for method, results, weight in (
        ("semantic", semantic_results, semantic_weight),
        ("lexical", lexical_results, lexical_weight),
    ):
        if weight == 0:
            continue

        seen = set()

        for rank, document in enumerate(results, 1):
            doc_id = document["document_id"]

            if doc_id in seen:
                continue

            seen.add(doc_id)

            if doc_id not in fused:
                fused[doc_id] = {
                    **document,
                    "rrf_score": 0.0,
                    "semantic_rank": None,
                    "lexical_rank": None,
                }

            entry = fused[doc_id]
            entry["rrf_score"] += weight / (k + rank)
            entry[f"{method}_rank"] = rank
            entry[f"{method}_score"] = document.get(
                f"{method}_score"
            )

    return sorted(
        fused.values(),
        key=lambda d: (
            -d["rrf_score"],
            d["document_id"],
        ),
    )[:limit]


def select_with_coverage(ranked, issue_tags, limit=3):
    if limit <= 0:
        raise ValueError("limit must be positive")

    requested = set(issue_tags)

    if not requested:
        return []

    eligible = [
        d for d in ranked
        if requested.intersection(d["issue_tags"])
    ]

    selected = []
    selected_ids = set()
    uncovered = set(requested)

    # Prefer the highest-ranked candidate covering
    # an issue that has not yet been represented.
    for document in eligible:
        doc_id = document["document_id"]

        if doc_id in selected_ids:
            continue

        matched = uncovered.intersection(
            document["issue_tags"]
        )

        if matched:
            selected.append(document)
            selected_ids.add(doc_id)
            uncovered.difference_update(matched)

        if len(selected) == limit or not uncovered:
            break

    # Fill remaining slots by original relevance rank.
    for document in eligible:
        if len(selected) == limit:
            break

        doc_id = document["document_id"]

        if doc_id not in selected_ids:
            selected.append(document)
            selected_ids.add(doc_id)

    return selected


def optimized_retrieve(
    connection,
    client,
    query,
    issue_tags,
    limit=3,
    semantic_weight=1.0,
    lexical_weight=0.25,
    ensure_coverage=True,
):
    if limit <= 0:
        raise ValueError("limit must be positive")

    if not query.strip() or not issue_tags:
        return []

    tags = sorted(set(issue_tags))
    candidate_limit = max(CANDIDATE_LIMIT, limit)

    embedding = embed_query(client, query)

    semantic = semantic_search(
        connection,
        embedding,
        tags,
        limit=candidate_limit,
    )

    lexical = relaxed_lexical_search(
        connection,
        query,
        tags,
        limit=candidate_limit,
    )

    ranked = weighted_rrf(
        semantic,
        lexical,
        semantic_weight=semantic_weight,
        lexical_weight=lexical_weight,
        limit=candidate_limit * 2,
    )

    if ensure_coverage:
        return select_with_coverage(ranked, tags, limit)

    return ranked[:limit]
