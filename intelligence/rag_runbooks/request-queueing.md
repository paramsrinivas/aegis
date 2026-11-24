# Backend request queueing
Tags: high_latency

## Symptoms
Request bursts or limited processing capacity can increase queue wait times, causing elevated response latency even when individual operations remain relatively fast.

## Diagnostic checks
Compare incoming request rate, active requests, queue depth, worker concurrency, and response duration. Check whether queue growth precedes EWMA increases. Inspect tail latency and peer replica behavior.

## Interpretation
Request volume alone is insufficient evidence of queueing. Prefer direct queue or worker saturation measurements, and distinguish queue wait time from downstream execution time.

## Safety
Do not adjust concurrency, scaling, or routing weights without human review.
