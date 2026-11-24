# Phase 5 — ADK Diagnostic Orchestration

## Overview

Aegis v2 introduces an optional Google ADK diagnostic
workflow integrated into the existing /explain endpoint.

The workflow consists of four sequential stages:

1. Deterministic incident triage.
2. Reviewed runbook retrieval.
3. Restricted LLM hypothesis selection.
4. Deterministic evidence and grounding validation.

The architecture uses one LLM agent and three
deterministic workflow stages.

## Dependencies

- google-adk==2.14.1
- google-genai==2.30.0

## Configuration

Agent orchestration is disabled by default.

AEGIS_AGENT_MODE=off preserves the legacy execution path.

Enable ADK and semantic retrieval:

    AEGIS_AGENT_MODE=adk \
    AEGIS_RAG_MODE=semantic_coverage \
    docker compose --profile rag up -d \
      --no-build --force-recreate intelligence-api

The intelligence image must be built before running
the above command.

## Safety Architecture

- SQLite remains the authoritative telemetry store.
- Incident severity is determined by application logic.
- The model selects only permitted hypothesis IDs.
- Evidence references must exist and support the selection.
- Cross-backend evidence references are rejected.
- Duplicate and unsupported hypotheses are rejected.
- Unexpected output fields and invalid types are rejected.
- Workflow sessions are isolated between requests.
- No remediation tools or autonomous actions are exposed.
- Human review is mandatory.
- Root causes are never marked as confirmed.

## Structured Output Compatibility

Provider-facing schemas omit the unsupported
additionalProperties JSON schema keyword.

Unexpected fields are preserved during provider-facing
model parsing so that strict local validation can reject
them instead of silently discarding them.

Separate strict schemas enforce the final output contract.

Adversarial workflow tests verify rejection of unexpected
top-level fields and unexpected hypothesis fields.

## Failure Handling

The workflow uses bounded execution time and explicit
Gemini client configuration.

If agent execution fails, the API returns deterministic
diagnostic information and local runbooks.

Fallback responses explicitly report degraded AI status,
agent fallback and retrieval fallback metadata.

The existing legacy endpoint behavior remains available.

## Verification

353 intelligence tests passed, including 43 new
Phase 5 tests.

Verified inside Docker:

- ADK and GenAI dependency installation.
- Dependency consistency.
- API health.
- Legacy response compatibility.
- Live incident telemetry.
- Live embedding generation and pgvector retrieval.
- ADK workflow execution with controlled model output.
- Deterministic grounding and safety invariants.
- Provider failure recovery.
- Missing API key recovery.
- Restoration of API credentials.

## Known Limitations

Successful live end-to-end ADK generation has not
yet been demonstrated.

Gemini generation requests repeatedly returned HTTP 503
with a provider-reported high-demand message.

A standalone generation request succeeded using
gemini-flash-lite-latest, but the subsequent complete
ADK request returned HTTP 503.

The controlled integration test used real telemetry,
real semantic retrieval and a mocked generation response.

This verifies orchestration and grounding integration,
not live LLM diagnostic quality.

The existing default model remains unchanged.

Workflow failure currently discards intermediate
retrieval results and returns deterministic runbooks.

No production reliability, autonomous remediation,
or live diagnostic accuracy claims are made.

Observability and expanded evaluation are addressed
in subsequent phases.
