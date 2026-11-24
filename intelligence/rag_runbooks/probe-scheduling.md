# Manager probe scheduling failures
Tags: unknown_latency

## Symptoms
Backend EWMA measurements may remain missing when the manager's periodic probe task does not start or stops executing.

## Diagnostic checks
Inspect manager startup logs, asynchronous task scheduling, probe timestamps, and task exceptions. Verify that probe execution continues after application startup and that measurements are periodically recorded.

## Interpretation
Absent EWMA indicates unknown latency, not zero latency. Confirm whether probes actually executed before diagnosing backend performance.

## Safety
Do not modify task scheduling or restart the manager without human approval.
