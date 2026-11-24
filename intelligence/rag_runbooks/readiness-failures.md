# Backend readiness failures
Tags: unhealthy

## Symptoms
A running backend process may report that it is not ready to serve traffic while initializing, waiting on dependencies, or recovering from an error.

## Diagnostic checks
Compare readiness responses with liveness behavior, container startup timestamps, dependency connectivity, and application initialization logs. Review recent changes and whether readiness recovers over successive probes.

## Interpretation
A running container is not necessarily a ready backend. Readiness failure does not automatically imply process failure or establish which dependency is responsible.

## Safety
Do not force a backend into service or restart it without human review.
