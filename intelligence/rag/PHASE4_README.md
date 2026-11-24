# Aegis Phase 4: opt-in RAG retrieval for `/explain`

## Safe default

`AEGIS_RAG_MODE=off` by default. Existing `/explain` JSON keys and v1 deterministic retrieval remain unchanged. No new external requests are made to the vector store when disabled. The SQLite incident and telemetry database remains authoritative. `main` is never modified by the installer; run it only on `feat/agentic-rag-v2`.

## Enable locally

Start the vector database separately with `docker compose --profile rag up -d vector-db` and ensure the twelve reviewed runbooks are already ingested. Set `AEGIS_RAG_MODE=semantic_coverage` in the root `.env` file, then rebuild/recreate the intelligence API with `docker compose --profile rag up -d --build intelligence-api`. If you customize `AEGIS_VECTOR_DB_PASSWORD`, use the same value in `.env` for both containers. To use an alternate database, set `AEGIS_VECTOR_DATABASE_URL` explicitly in `.env` (never commit credentials).

The API connects to the private Docker Compose `vector-db` service, embeds incident text using Gemini `RETRIEVAL_QUERY`, retrieves a top-ten tag-gated semantic ranking, applies deterministic tag coverage for up to three documents, and validates exact source paths, content, tags, titles and SHA-256 hashes against the local reviewed files. Retrieved documents are passed to the **existing** grounded hypothesis selection code, not to a new unrestricted generation mechanism.

When enabled, the `/explain` response includes:

- `retrieval.mode`: `semantic_coverage` or `deterministic_fallback`
- `retrieval.fallback`: boolean
- `retrieval.reason`: `null`, `no_eligible_tags`, `invalid_rag_mode`, or `rag_unavailable`

If the vector DB, embedding provider, retrieval, integrity checks, or configuration fail, the route logs only the error class and uses the existing deterministic runbooks. A retrieval fallback is not the same as an AI fallback: Gemini can still generate a grounded explanation using v1 runbooks. The existing AI failure path remains unchanged.

## Return to v1 behavior

Remove `AEGIS_RAG_MODE` or set it to `off`, then recreate `intelligence-api`. This excludes the additional `retrieval` response field and requires no vector DB. The pgvector corpus, local evaluation artifacts and optional Docker service are left in place.

## Validation

```bash
cd intelligence
../.venv/bin/python -m pytest -q tests -p no:cacheprovider
cd ..
docker compose config --quiet
git diff --check
```

Then smoke-test an API restart with the flag **off**, confirm `/healthz` and `/explain`, and only then enable the flag and repeat against the running profile-gated vector database. Confirm `retrieval.mode`, `review_required=true`, and `actions_executed=[]`. A failure to retrieve should return `deterministic_fallback`, not an HTTP 500.

## Limitations

- Twelve assistant-authored synthetic runbooks; not production-verified operational guidance.
- Tag-gating does not establish that a returned document is relevant or that a root cause has been proven.
- Embedding model calls add latency. The test suite mocks external dependencies; live Docker smoke tests are required.
- This integration does not implement ADK agents, observability, retry/circuit-breaking for retrieval, live end-to-end latency measurements, or automated remediation.
- The vector database must remain on the private Docker network; do not publish its port or commit real passwords or API keys.
