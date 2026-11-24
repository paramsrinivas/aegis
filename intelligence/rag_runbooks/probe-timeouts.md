# Telemetry probe timeouts
Tags: unknown_latency

## Symptoms
Manager probes may exceed their configured timeout without producing a valid latency sample.

## Diagnostic checks
Inspect probe timeout settings, elapsed durations, HTTP outcomes, connection errors, and repeated probe attempts. Compare the timing of failures across backends and correlate with available application logs.

## Interpretation
A timeout does not establish whether the underlying cause is network delay, backend overload, or dependency latency. Missing samples must not be interpreted as zero-duration responses.

## Safety
Do not increase timeout values or change routing decisions without human review.
