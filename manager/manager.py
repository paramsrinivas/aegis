# manager/manager.py
import asyncio
import time
from fastapi import FastAPI
import uvicorn
import httpx
from prometheus_client import Gauge, generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response

app = FastAPI()
BACKENDS = [
    {"name": "backend1", "url": "http://backend1:8101"},
    {"name": "backend2", "url": "http://backend2:8102"},
    {"name": "backend3", "url": "http://backend3:8103"},
]
EWMA_ALPHA = 0.3

weights_gauge = Gauge("aegis_backend_weight", "Backend weight", ["backend"])
latency_gauge = Gauge("aegis_backend_lat_ms", "Backend EWMA latency ms", ["backend"])
health_gauge = Gauge("aegis_backend_health", "Backend health 1/0", ["backend"])

state = {b["name"]: {"ewma": None, "healthy": 1} for b in BACKENDS}

async def probe_loop():
    async with httpx.AsyncClient(timeout=3.0) as client:
        while True:
            for b in BACKENDS:
                name = b["name"]
                try:
                    t0 = time.time()
                    r = await client.get(b["url"] + "/infer", timeout=2.0)
                    latency = (time.time() - t0) * 1000
                    prev = state[name]["ewma"]
                    state[name]["ewma"] = latency if prev is None else (EWMA_ALPHA*latency + (1-EWMA_ALPHA)*prev)
                    state[name]["healthy"] = 1
                except Exception:
                    state[name]["healthy"] = 0
                    state[name]["ewma"] = (state[name]["ewma"] or 1000) * 1.5
                latency_gauge.labels(name).set(state[name]["ewma"] or 0)
                health_gauge.labels(name).set(state[name]["healthy"])
            total = 0.0
            invs = {}
            for name, s in state.items():
                val = s["ewma"] or 1000.0
                inv = (1.0 / val) if s["healthy"]==1 else 0.0001
                invs[name] = inv
                total += inv
            for name, inv in invs.items():
                w = (inv / total) if total > 0 else 1.0/len(BACKENDS)
                weights_gauge.labels(name).set(w)
            await asyncio.sleep(1.0)

@app.get("/weights")
def weights():
    return {name: {"ewma_ms": state[name]["ewma"], "healthy": state[name]["healthy"]} for name in state}

@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(probe_loop())
    uvicorn.run(app, host="0.0.0.0", port=8001)
