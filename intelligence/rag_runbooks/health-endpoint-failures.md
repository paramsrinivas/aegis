# Backend health endpoint failures
Tags: unhealthy

## Symptoms
Health probes may receive HTTP errors or unexpected responses even when some application endpoints remain accessible.

## Diagnostic checks
Record the health endpoint status code, response body, probe timestamp, and recent application logs. Compare health endpoint behavior with readiness and actual request-serving behavior. Check whether the failure is repeatable.

## Interpretation
An application-generated HTTP error differs from a transport failure. A failed health check does not, by itself, prove that every application request will fail.

## Safety
Do not restart or remove a backend from service without human review and approval.
