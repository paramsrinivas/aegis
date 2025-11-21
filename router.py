# router_fixed.py (with Prometheus metrics)
import traceback
import httpx
import time
from fastapi import FastAPI, Response
from manager_client import ManagerClient
import asyncio
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

app = FastAPI()
MANAGER_HOST = "manager"
MANAGER_PORT = 8001
BACKEND_PORTS = {"backend1": 8101, "backend2": 8102, "backend3": 8103}

# Prometheus metrics
REQ_LATENCY = Histogram('aegis_router_request_latency_ms', 'Request latency in milliseconds', ['endpoint'])
REQ_COUNT = Counter('aegis_router_requests_total', 'Total requests', ['endpoint', 'status'])

@app.on_event('startup')
async def startup():
    app.state.http = httpx.AsyncClient(timeout=10.0)
    app.state.manager_client = ManagerClient(host=MANAGER_HOST, port=MANAGER_PORT)

@app.on_event('shutdown')
async def shutdown():
    try:
        await app.state.http.aclose()
    except Exception:
        pass
    try:
        await app.state.manager_client.close()
    except Exception:
        pass

def choose_backend(weights):
    healthy = [k for k,v in weights.items() if v.get('healthy',0)]
    if not healthy:
        return None
    return healthy[0]

@app.get('/healthz')
async def healthz():
    REQ_COUNT.labels(endpoint='/healthz', status='200').inc()
    return {'status': 'ok'}

@app.get('/metrics')
async def metrics():
    # Expose Prometheus metrics
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)

@app.get('/predict')
async def predict():
    start = time.perf_counter()
    endpoint = '/predict'
    try:
        mc = app.state.manager_client
        weights = await mc.get_weights()
        backend = choose_backend(weights)
        if not backend:
            REQ_COUNT.labels(endpoint=endpoint, status='503').inc()
            return {'error':'no backend available'}
        port = BACKEND_PORTS.get(backend, 8101)
        resp = await app.state.http.get(f'http://{backend}:{port}/predict', timeout=10.0)
        resp.raise_for_status()
        result = resp.json()
        latency_ms = (time.perf_counter() - start) * 1000.0
        REQ_LATENCY.labels(endpoint=endpoint).observe(latency_ms)
        REQ_COUNT.labels(endpoint=endpoint, status=str(resp.status_code)).inc()
        return result
    except Exception as e:
        traceback.print_exc()
        latency_ms = (time.perf_counter() - start) * 1000.0
        REQ_LATENCY.labels(endpoint=endpoint).observe(latency_ms)
        REQ_COUNT.labels(endpoint=endpoint, status='500').inc()
        return {'error': str(e)}
