# router/router.py
import time
from fastapi import FastAPI, Request
import uvicorn
import httpx
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response
import random

app = FastAPI()
REQUESTS = Counter("router_requests_total", "Total incoming requests")
FAILED = Counter("router_failed_total", "Failed forwarded requests")
LATENCY = Histogram("router_latency_seconds", "Router e2e latency seconds")
BACKEND_CHOSEN = Counter("router_backend_chosen_total", "Which backend chosen", ["backend"])
ROUTER_QUEUE = Gauge("router_queue_depth", "Router queue depth")

MANAGER_URL = "http://manager:8001"

mapping = {"backend1": "http://backend1:8101", "backend2": "http://backend2:8102", "backend3": "http://backend3:8103"}

async def get_weights():
    async with httpx.AsyncClient() as client:
        try:
            r = await client.get(MANAGER_URL + "/weights", timeout=2.0)
            return r.json()
        except Exception:
            return None

async def select_backend(weights):
    if not weights:
        return random.choice(list(mapping.keys()))
    invs = {}
    total = 0.0
    for name, v in weights.items():
        ewma = v.get("ewma_ms") or 1000.0
        healthy = v.get("healthy", 1)
        inv = (1.0/ewma) if healthy==1 else 0.0001
        invs[name] = inv
        total += inv
    r = random.random()*total
    upto = 0.0
    for name, inv in invs.items():
        upto += inv
        if r <= upto:
            return name
    return list(invs.keys())[0]

@app.get("/predict")
async def predict(request: Request):
    REQUESTS.inc()
    start = time.time()
    weights = await get_weights()
    backend_name = await select_backend(weights)
    BACKEND_CHOSEN.labels(backend_name).inc()
    url = mapping[backend_name] + "/infer"
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            r = await client.get(url, timeout=5.0)
            LATENCY.observe(time.time() - start)
            return r.json()
        except Exception as e:
            FAILED.inc()
            return {"error": "backend failure", "detail": str(e)}

@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
