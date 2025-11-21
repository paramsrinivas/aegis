# manager.py
from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel
import time
import math
import threading

# Prometheus client (safe/idempotent registration)
from prometheus_client import (
    CollectorRegistry,
    Gauge,
    Counter,
    REGISTRY,
    generate_latest,
    CONTENT_TYPE_LATEST,
)

app = FastAPI()

# --- safe prometheus metrics init (idempotent) ---
# Use the global REGISTRY and avoid duplicate registration on repeated imports.
registry = REGISTRY

def _make_metric_safe(constructor, name, documentation, labelnames=None):
    """
    Return an existing collector if one with the same name exists,
    otherwise register a new one. Works around duplicate registration
    when a module is imported multiple times or uvicorn reloads workers.
    """
    # internal mapping exists on REGISTRY in current prometheus_client implementation
    existing = getattr(REGISTRY, "_names_to_collectors", None)
    if existing and name in existing:
        return existing[name]
    try:
        if labelnames:
            return constructor(name, documentation, labelnames, registry=registry)
        else:
            return constructor(name, documentation, registry=registry)
    except Exception:
        # If race or constructor signature mismatch, try to return existing if available.
        existing = getattr(REGISTRY, "_names_to_collectors", None)
        if existing and name in existing:
            return existing[name]
        raise
# create metrics (idempotent)
weight_g = _make_metric_safe(Gauge, "aegis_backend_weight", "Backend weight", ["backend"])
latency_g = _make_metric_safe(Gauge, "aegis_backend_lat_ms", "Backend EWMA latency ms", ["backend"])
health_g = _make_metric_safe(Gauge, "aegis_backend_health", "Backend health 1/0", ["backend"])
record_c = _make_metric_safe(Counter, "aegis_manager_record_total", "Records received by manager")
record_created = _make_metric_safe(Gauge, "aegis_manager_record_created", "Records received by manager")
# --- end safe prometheus init ---

# in-memory EWMA state per backend
class BackendState:
    def __init__(self, alpha=0.3):
        self.alpha = alpha
        self.ewma_latency = None
        self.count = 0
        self.last_ts = None

    def add_sample(self, sample):
        self.count += 1
        if self.ewma_latency is None:
            self.ewma_latency = sample
        else:
            self.ewma_latency = self.alpha * sample + (1 - self.alpha) * self.ewma_latency
        self.last_ts = time.time()

    def get_score(self):
        # lower latency -> higher weight. transform ewma to weight
        if self.ewma_latency is None:
            return 1.0
        return 1.0 / (0.001 + self.ewma_latency)

# global state
BACKENDS = ["backend1", "backend2", "backend3"]
state = {b: BackendState(alpha=0.2) for b in BACKENDS}
manual_weights = {}  # manual overrides (float values)

@app.post("/record")
async def record(payload: dict):
    """
    router posts {"backend": "backend1", "latency_s": 0.05, "status_code": 200}
    """
    try:
        b = payload.get("backend")
        lat = float(payload.get("latency_s", 0.0))
    except Exception:
        raise HTTPException(status_code=400, detail="bad payload")

    if not b:
        raise HTTPException(status_code=400, detail="missing backend")

    if b not in state:
        state[b] = BackendState(alpha=0.2)
    state[b].add_sample(lat)

    # update prometheus metrics (safe to call repeatedly)
    try:
        # set latency gauge (ms)
        latency_g.labels(backend=b).set(lat * 1e3)
    except Exception:
        # if latency_g is a collector object (existing registration), attempt attribute access
        try:
            latency_g.labels(backend=b).set(lat * 1e3)
        except Exception:
            pass

    try:
        # set weight derived from EWMA
        weight = state[b].get_score()
        weight_g.labels(backend=b).set(weight)
    except Exception:
        pass

    # health is boolean 1/0 (we assume healthy on record)
    try:
        health_g.labels(backend=b).set(1.0)
    except Exception:
        pass

    # increment record counter and update created gauge (timestamp-ish)
    try:
        record_c.inc()
        record_created.set(time.time())
    except Exception:
        pass

    return {"status": "ok"}

@app.get("/weights")
async def get_weights():
    # if manual_weights set, return them; else compute from EWMA
    if manual_weights:
        return manual_weights
    out = {}
    for b, s in state.items():
        out[b] = s.get_score()
    return out

class WeightsIn(BaseModel):
    __root__: dict

@app.post("/weights")
async def set_weights(wi: WeightsIn):
    # set manual override - replace manual_weights
    d = dict(wi.__root__)
    cleaned = {}
    for k, v in d.items():
        try:
            cleaned[k] = float(v)
        except Exception:
            try:
                cleaned[k] = float(v.get("weight", 1.0))
            except Exception:
                cleaned[k] = 1.0
    # update manual override map
    manual_weights.clear()
    manual_weights.update(cleaned)

    # reflect manual weights into prometheus gauges too
    for bk, val in cleaned.items():
        try:
            weight_g.labels(backend=bk).set(val)
        except Exception:
            pass

    return {"status": "ok", "applied": manual_weights}

@app.delete("/weights")
async def clear_weights():
    manual_weights.clear()
    return {"status": "ok"}

@app.get("/metrics")
async def metrics():
    """
    Expose Prometheus metrics in the standard text format.
    """
    payload = generate_latest(registry)
    return Response(content=payload, media_type=CONTENT_TYPE_LATEST)

# small health endpoint
@app.get("/healthz")
async def healthz():
    return {"status": "ok"}

