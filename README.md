Aegis is a lightweight distributed system that simulates a production-grade microservice environment with:

A Router Service that routes incoming requests to multiple backend replicas.

A Manager Service that dynamically autoscale backends based on performance.

A set of Backend Services that simulate load and latency.

A fully reproducible benchmarking suite to measure:

Baseline performance

Routing performance

Fault-handling and failover

Built-in instrumentation for Prometheus & Grafana (optional).

Aegis demonstrates real-world concepts:
load balancing, fault tolerance, autoscaling, system health monitoring, latency analysis, and distributed coordination.

Features
🔹 1. Intelligent Router

Weighted routing

Monitors backend latency live

Automatically avoids bad/slow nodes

Implements health checks

Graceful failover on backend failure

🔹 2. Backend Microservices

Lightweight FastAPI servers

Simulated workload (sleep-based)

Random failure injection modes

🔹 3. Autoscaling Manager

Observes backend performance

Scales backend replicas up/down

Communicates via REST APIs

🔹 4. Benchmarking Suite

Located in /bench/:

py_baseline.py – no router, direct backend hit

py_router_test.py – routed load test

py_simple_fail.py – failure handling benchmark

autoscaler.py – evaluates scaling decisions

pyloadgen.py – configurable load generator

🔹 5. Analysis Tools

Located in /analysis/:

analyze.py generates:

Summary statistics

Latency distributions

Backend usage distribution

Charts saved to analysis/summary.png

Project Structure
aegis/
│
├── router/                # Router microservice
├── backend/               # Backend service template
├── manager/               # Autoscaling manager
│
├── bench/                 # Benchmarking scripts
├── analysis/              # Data analysis + plotting tools
│
├── docker-compose.yml     # Multi-service environment
├── requirements.txt
└── README.md

Tech Stack

Python 3.11

FastAPI

Uvicorn

Docker + Docker Compose

Prometheus / Grafana (optional)

Matplotlib, Pandas for analysis

