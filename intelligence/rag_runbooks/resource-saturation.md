# Backend resource saturation
Tags: high_latency

## Symptoms
Sustained CPU pressure, memory contention, garbage collection pauses, or overloaded workers may coincide with increased backend request latency.

## Diagnostic checks
Compare EWMA latency trends against CPU, memory, request volume, and worker utilization over the same interval. Compare affected replicas with healthy peers. Check whether resource pressure preceded the latency increase.

## Interpretation
High resource utilization alone does not establish the root cause. Verify timing, persistence, and request impact before attributing latency to resource saturation.

## Safety
Do not resize, restart, or modify routing weights without human review and approval.
