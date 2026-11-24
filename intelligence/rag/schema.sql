
-- Aegis v2: hybrid RAG document store
-- SQLite remains the authoritative incident/telemetry store.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS rag_documents (
    document_id TEXT PRIMARY KEY,
    source_path TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    issue_tags TEXT[] NOT NULL DEFAULT '{}',
    content_sha256 CHAR(64) NOT NULL,
    embedding_model TEXT NOT NULL,
    embedding vector(768),
    search_vector tsvector GENERATED ALWAYS AS (
        to_tsvector(
            'english',
            coalesce(title, '') || ' ' || coalesce(content, '')
        )
    ) STORED,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS rag_documents_fts_idx
    ON rag_documents USING GIN (search_vector);

CREATE INDEX IF NOT EXISTS rag_documents_tags_idx
    ON rag_documents USING GIN (issue_tags);

CREATE INDEX IF NOT EXISTS rag_documents_embedding_idx
    ON rag_documents
    USING hnsw (embedding vector_cosine_ops);

