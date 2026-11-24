# Downstream dependency latency
Tags: high_latency

## Symptoms
Backend response latency may rise when calls to databases, external APIs, or other downstream services become slow.

## Diagnostic checks
Inspect dependency request duration, connection pool waits, timeout rates, and application traces when available. Compare backend EWMA against downstream latency over matching time windows. Identify whether multiple replicas share the affected dependency.

## Interpretation
A slow backend response does not prove that a dependency is responsible. Require supporting dependency measurements or traces before selecting this hypothesis.

## Safety
Do not change dependency configuration, timeouts, or traffic routing without human approval.
