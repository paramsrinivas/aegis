# Backend network connectivity failures
Tags: unhealthy

## Symptoms
Connection refusals, DNS resolution failures, network timeouts, or interrupted connections may prevent health probes from reaching a backend.

## Diagnostic checks
Inspect probe transport errors, container network membership, service discovery, listening ports, and backend process status. Compare connectivity from the manager with connectivity between other services. Distinguish network failures from HTTP responses.

## Interpretation
A timeout does not uniquely identify a network fault. A slow application or overloaded dependency can also delay a response. Confirm the failure layer before attributing cause.

## Safety
Do not change network configuration or restart services without human approval.
