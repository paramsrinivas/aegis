# backend/app.py
import argparse
import random
import time
from fastapi import FastAPI, HTTPException
import uvicorn
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response

app = FastAPI()
REQUESTS = Counter("backend_requests_total", "Total requests")
LATENCY = Histogram("backend_latency_seconds", "Backend latency seconds")
ERRORS = Counter("backend_errors_total", "Backend errors")
HEALTH = Gauge("backend_health_status", "1=healthy,0=unhealthy")

@app.get("/infer")
async def infer():
    REQUESTS.inc()
    start = time.time()
    if random.random() < app.state.error_rate:
        ERRORS.inc()
        HEALTH.set(0)
        raise HTTPException(status_code=500, detail="simulated error")
    wait = max(0, random.uniform(-app.state.jitter, app.state.jitter) + app.state.latency) / 1000.0
    time.sleep(wait)
    LATENCY.observe(time.time() - start)
    HEALTH.set(1)
    return {"status": "ok", "backend_port": app.state.port, "latency_ms": wait*1000}

@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=8101)
    p.add_argument("--latency", type=int, default=100)
    p.add_argument("--jitter", type=int, default=20)
    p.add_argument("--error", type=float, default=0.01)
    args = p.parse_args()
    app.state.latency = args.latency
    app.state.jitter = args.jitter
    app.state.error_rate = args.error
    app.state.port = args.port
    uvicorn.run(app, host="0.0.0.0", port=args.port)
