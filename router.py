import os
import random
import time

import httpx
from fastapi import FastAPI, HTTPException
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.responses import Response

app = FastAPI()
MANAGER_URL = os.getenv("MANAGER_URL", "http://manager:8001")
BACKENDS = {
    "backend1": "http://backend1:8101",
    "backend2": "http://backend2:8102",
    "backend3": "http://backend3:8103",
}
REQUESTS = Counter("router_requests_total", "Total incoming requests")
FAILED = Counter("router_failed_total", "Failed forwarded requests")
LATENCY = Histogram("router_latency_seconds", "Router end-to-end latency seconds")
BACKEND_CHOSEN = Counter("router_backend_chosen_total", "Backend selected", ["backend"])

def choose_backend(weights):
    if not isinstance(weights, dict):
        raise HTTPException(503, "Backend health unavailable")
    eligible = {}
    for name in BACKENDS:
        info = weights.get(name, {})
        if not isinstance(info, dict) or info.get("healthy") != 1:
            continue
        ewma = info.get("ewma_ms")
        if isinstance(ewma, (int, float)) and 0 < ewma < float("inf"):
            eligible[name] = 1.0 / ewma
    if not eligible:
        raise HTTPException(503, "No healthy backends")
    return random.choices(list(eligible), weights=list(eligible.values()), k=1)[0]

@app.get("/healthz")
async def healthz():
    return {"status": "ok"}

@app.get("/predict")
async def predict():
    REQUESTS.inc()
    start = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            try:
                manager = await client.get(f"{MANAGER_URL}/weights")
                manager.raise_for_status()
                weights = manager.json()
            except (httpx.HTTPError, ValueError) as exc:
                raise HTTPException(503, "Manager unavailable") from exc
            name = choose_backend(weights)
            BACKEND_CHOSEN.labels(name).inc()
            try:
                upstream = await client.get(f"{BACKENDS[name]}/infer")
                upstream.raise_for_status()
                payload = upstream.json()
            except (httpx.HTTPError, ValueError) as exc:
                raise HTTPException(502, "Backend request failed") from exc
            if payload.get("status") != "ok":
                raise HTTPException(502, "Backend returned failure")
            return payload
    except HTTPException:
        FAILED.inc()
        raise
    finally:
        LATENCY.observe(time.perf_counter() - start)

@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
