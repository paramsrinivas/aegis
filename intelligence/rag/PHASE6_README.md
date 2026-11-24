# Phase 6 — Diagnostic Observability

## Overview

Aegis v2 provides structured JSON diagnostic events
for the optional ADK execution path.

Observability uses Python standard-library logging,
ContextVar-based trace isolation and monotonic timing.

No additional dependencies or external tracing
infrastructure are required.

## Instrumentation

Each ADK service invocation receives a unique trace ID.

Recorded stages include:

- Diagnostic service execution
- ADK workflow execution
- Deterministic triage
- Runbook retrieval
- Gemini generation
- Deterministic grounding
- Deterministic fallback

Structured event types:

- diagnostic_stage
- diagnostic_outcome
- retrieval_metrics
- model_usage

## Model Metrics

ObservedGemini extends the installed ADK Gemini model
and preserves its async-generator response interface.

The model wrapper records execution duration and
provider-reported token counts.

Missing token metadata is represented as null,
not zero.

Model timing includes SDK execution overhead and
is not an isolated network latency measurement.

## Retrieval Metrics

Retrieval events record the selected strategy,
document count, fallback status and classified reason.

Document contents and raw retrieval queries are
not included in these application trace events.

## Failure Classification

Diagnostic outcomes distinguish successful AI execution
from deterministic recovery.

Supported failure classifications:

- missing_api_key
- provider_unavailable
- provider_rate_limited
- provider_error
- timeout
- validation_error
- internal_error

Explicit exception causes are inspected to support
wrapped provider errors.

## Privacy

Application trace events exclude raw prompts,
model responses, exception messages, credentials
and runbook contents.

The diagnostic logger emits structured JSON to stderr.

This is not a comprehensive audit of all third-party
SDK logging or telemetry.

## Verification

385 intelligence tests passed, including 32 new
Phase 6 observability tests.

Live Docker verification confirmed:

- Cached dependency build
- Healthy intelligence API
- Correlated structured trace events
- Live semantic retrieval of three reviewed runbooks
- Model execution failure instrumentation
- Provider failure classification
- Deterministic fallback
- Missing token metadata handling
- Preservation of safety invariants

## Example Runtime Measurement

One live diagnostic request recorded:

- Triage: 0.061 ms
- Retrieval: 859.717 ms
- Gemini execution: 2622.929 ms
- Workflow: 3569.964 ms
- Fallback: 1.468 ms
- Diagnostic service: 4176.876 ms

The AI outcome was degraded with reason
provider_unavailable.

These measurements describe one request and are
not a latency benchmark or production SLA.

## Known Limitations

Successful live Gemini generation and live token
counts remain unverified.

Trace scope begins at the ADK service boundary,
not the complete HTTP request lifecycle.

The request stage measures service completion,
while diagnostic_outcome describes AI availability.

Generator cancellation behavior has not been
fully verified against the live provider.

Retrieval metrics describe the workflow retrieval
stage, which may differ from the final runbooks
returned after agent failure.

No distributed tracing backend, persistent trace
store, or external metrics exporter is implemented.

The existing API response contract and deterministic
safety architecture remain unchanged.
