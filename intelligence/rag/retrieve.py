
"""Hybrid runbook retrieval using pgvector, PostgreSQL FTS and RRF."""

from google.genai import types
from psycopg.rows import dict_row

from rag.ingest import (
    EMBEDDING_MODEL,
    EMBEDDING_DIMENSIONS,
    validate_embedding,
)


RRF_K = 60
CANDIDATE_LIMIT = 10
RESULT_LIMIT = 3


def embed_query(client, query):
    """Generate a retrieval-specific query embedding."""
    response = client.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=query,
        config=types.EmbedContentConfig(
            task_type="RETRIEVAL_QUERY",
            output_dimensionality=EMBEDDING_DIMENSIONS,
        ),
    )

    if not response.embeddings or not response.embeddings[0].values:
        raise ValueError("Query embedding API returned no values")

    return validate_embedding(response.embeddings[0].values)


def semantic_search(
    connection,
    embedding,
    issue_tags,
    limit=CANDIDATE_LIMIT,
):
    """Retrieve eligible documents by cosine similarity."""
    if not issue_tags:
        return []

    embedding = validate_embedding(embedding)
    vector_literal = "[" + ",".join(str(v) for v in embedding) + "]"

    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT
                document_id,
                source_path,
                title,
                content,
                issue_tags,
                content_sha256,
                1 - (embedding <=> %s::vector) AS semantic_score
            FROM rag_documents
            WHERE issue_tags && %s::text[]
              AND embedding_model = %s
              AND embedding IS NOT NULL
            ORDER BY embedding <=> %s::vector, document_id
            LIMIT %s
            """,
            (
                vector_literal,
                issue_tags,
                EMBEDDING_MODEL,
                vector_literal,
                limit,
            ),
        )

        return cursor.fetchall()


def lexical_search(
    connection,
    query,
    issue_tags,
    limit=CANDIDATE_LIMIT,
):
    """Retrieve eligible documents using PostgreSQL full-text search."""
    if not issue_tags or not query.strip():
        return []

    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT
                document_id,
                source_path,
                title,
                content,
                issue_tags,
                content_sha256,
                ts_rank(
                    search_vector,
                    plainto_tsquery('english', %s)
                ) AS lexical_score
            FROM rag_documents
            WHERE issue_tags && %s::text[]
              AND search_vector @@ plainto_tsquery('english', %s)
            ORDER BY lexical_score DESC, document_id
            LIMIT %s
            """,
            (query, issue_tags, query, limit),
        )

        return cursor.fetchall()


def reciprocal_rank_fusion(
    semantic_results,
    lexical_results,
    k=RRF_K,
    limit=RESULT_LIMIT,
):
    """Combine retrieval rankings without mixing raw score scales."""
    if k <= 0 or limit <= 0:
        raise ValueError("k and limit must be positive")

    fused = {}

    for method, results in (
        ("semantic", semantic_results),
        ("lexical", lexical_results),
    ):
        seen = set()

        for rank, document in enumerate(results, start=1):
            document_id = document["document_id"]

            if document_id in seen:
                continue

            seen.add(document_id)

            if document_id not in fused:
                fused[document_id] = {
                    **document,
                    "rrf_score": 0.0,
                    "semantic_rank": None,
                    "lexical_rank": None,
                }

            entry = fused[document_id]

            entry["rrf_score"] += 1 / (k + rank)
            entry[f"{method}_rank"] = rank
            entry[f"{method}_score"] = document.get(
                f"{method}_score"
            )

    return sorted(
        fused.values(),
        key=lambda document: (
            -document["rrf_score"],
            document["document_id"],
        ),
    )[:limit]


def hybrid_retrieve(
    connection,
    client,
    query,
    issue_tags,
    limit=RESULT_LIMIT,
):
    """Retrieve and fuse relevant reviewed runbooks."""
    if limit <= 0:
        raise ValueError("limit must be positive")

    if not query.strip() or not issue_tags:
        return []

    tags = sorted(set(issue_tags))
    candidate_limit = max(CANDIDATE_LIMIT, limit)

    embedding = embed_query(client, query)

    semantic_results = semantic_search(
        connection,
        embedding,
        tags,
        limit=candidate_limit,
    )

    lexical_results = lexical_search(
        connection,
        query,
        tags,
        limit=candidate_limit,
    )

    return reciprocal_rank_fusion(
        semantic_results,
        lexical_results,
        limit=limit,
    )

