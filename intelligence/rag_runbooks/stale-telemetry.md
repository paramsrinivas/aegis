# Stale backend telemetry
Tags: unknown_latency

## Symptoms
A previously valid EWMA measurement may become outdated when fresh probes or metric updates stop arriving.

## Diagnostic checks
Compare the last successful probe timestamp against the current observation time and the expected probe interval. Inspect metric publication, persistence, and manager task health. Check whether displayed values are historical rather than current.

## Interpretation
A historical EWMA value does not prove present backend health. Distinguish missing measurements, stale measurements, and newly recorded measurements.

## Safety
Do not infer current performance from stale values or modify routing without human approval.
