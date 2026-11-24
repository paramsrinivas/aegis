# Aegis v2 — Consolidated Evaluation

## Evaluation Scope

Aegis v2 extends the original infrastructure intelligence
platform with reviewed-document retrieval, pgvector,
Google ADK orchestration and structured observability.

Evaluation combines automated regression tests, synthetic
retrieval datasets, controlled model responses and live
local Docker integration checks.

## Regression Testing

| Milestone | Intelligence tests |
|---|---:|
| Aegis v1 | 232 |
| Hybrid retrieval infrastructure | 260 |
| Expanded corpus | 261 |
| Initial retrieval evaluation | 265 |
| Coverage-aware retrieval | 288 |
| Runtime RAG integration | 310 |
| ADK orchestration | 353 |
| Structured observability | 385 |

The latest verified intelligence suite passed 385 tests.

This represents 153 additional tests over v1,
or 65.9% growth in test count.

Test count growth is not equivalent to measured
code coverage.

## Retrieval Corpus

The reviewed corpus contains 12 operational runbooks:

- 4 high-latency runbooks
- 4 unhealthy-backend runbooks
- 4 missing-telemetry runbooks

Document provenance includes stable identifiers,
source paths, issue tags and SHA-256 content hashes.

Embeddings use gemini-embedding-001 with 768 dimensions.

## Retrieval Evaluation

The initial development dataset contains 42 synthetic
queries. A subsequent validation dataset contains 30
additional synthetic queries.

The validation dataset includes 16 single-issue,
8 multi-issue and 6 negative cases.

### Validation Results

| Strategy | Hit@1 | Recall@3 | MRR@3 | Multi-issue recall | Multi-issue coverage |
|---|---:|---:|---:|---:|---:|
| Semantic | 87.50% | 86.81% | 0.8958 | 72.92% | 89.58% |
| Semantic + coverage | 87.50% | 88.19% | 0.8958 | 77.08% | 100% |
| Weighted hybrid + coverage | 79.17% | 86.11% | 0.8542 | 70.83% | 100% |
| Adaptive | 87.50% | 86.11% | 0.8958 | 70.83% | 100% |

All four strategies achieved 100% rejection of the
six negative cases and zero measured tag leakage.

Semantic retrieval with coverage was selected for
runtime integration.

Relative to semantic-only retrieval, it improved:

- Recall@3 by 1.39 percentage points.
- Multi-issue recall by 4.17 percentage points.
- Multi-issue tag coverage by 10.42 percentage points.

Hit@1 and MRR@3 remained unchanged.

Hybrid retrieval remains implemented and evaluated,
but is not the selected runtime default.

The validation dataset informed strategy selection
and is therefore not an independent final holdout.

## Live Retrieval Smoke Checks

The final Docker smoke check used real Gemini embeddings
and the populated pgvector database.

| Case | Documents | Issue coverage | Duration |
|---|---:|---:|---:|
| High latency | 3 | 1/1 | 509.37 ms |
| Unhealthy backend | 3 | 1/1 | 435.37 ms |
| Unknown latency | 3 | 1/1 | 454.57 ms |
| Mixed incident | 3 | 2/2 | 443.17 ms |
| Three-issue incident | 3 | 3/3 | 472.80 ms |

Mean positive-query wall-clock duration: 463.05 ms.

Additional checks:

- Reviewed corpus integrity: PASS
- Unsupported issue rejection: PASS
- Empty tag rejection: PASS
- Empty query rejection: PASS

Total live smoke checks: 9/9 passed.

These measurements describe five positive queries
in one local integration run, not production latency
or statistically robust performance estimates.

## ADK Workflow Evaluation

The diagnostic workflow consists of deterministic
triage, reviewed-document retrieval, one restricted
LLM hypothesis-selection agent and deterministic
grounding validation.

Controlled model responses verified the workflow
with live telemetry and live semantic retrieval.

Regression tests cover malformed output, unsupported
hypotheses, fabricated evidence, cross-backend
references, duplicate selections, concurrent execution,
timeouts and deterministic fallback.

Successful live end-to-end Gemini generation remains
unverified in v2 because provider requests returned
unavailable errors during integration testing.

## Observability Evaluation

Live Docker execution verified correlated JSON events,
retrieval metrics, model execution timing, classified
provider failures and deterministic recovery.

One degraded diagnostic invocation recorded:

| Stage | Duration |
|---|---:|
| Triage | 0.061 ms |
| Retrieval | 859.717 ms |
| Gemini execution | 2622.929 ms |
| Workflow | 3569.964 ms |
| Fallback | 1.468 ms |
| Diagnostic service | 4176.876 ms |

The provider failure was classified as
provider_unavailable.

Missing token counts were represented as null.

Live successful token reporting remains unverified.
Token reporting behavior is covered by controlled tests.

Trace scope is the ADK diagnostic service invocation,
not the complete HTTP request lifecycle.

## Safety Boundaries

- Severity remains deterministic.
- SQLite remains authoritative for telemetry and incidents.
- Retrieved documents are validated against reviewed files.
- Hypotheses require valid backend-specific evidence.
- Root causes remain unconfirmed.
- Human review is required.
- No autonomous remediation is implemented.
- Provider failure preserves deterministic diagnostics.

## Evaluation Limitations

The retrieval datasets are synthetic and use
application-defined relevance labels.

Issue-tag coverage does not establish document
relevance or root-cause accuracy.

The negative cases primarily test input and tag gating,
not semantic rejection of every irrelevant query.

Controlled model responses verify orchestration and
validation, not independent model reasoning quality.

The project does not establish production reliability,
large-scale retrieval performance or comprehensive
security guarantees.

## Conclusion

Aegis v2 demonstrates a locally integrated,
evaluation-driven RAG and agent orchestration
architecture with deterministic safety boundaries
and structured diagnostic observability.

The implementation favors measured retrieval quality
and graceful degradation over unnecessary model
autonomy or architectural complexity.
