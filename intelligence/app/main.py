import os
import math
import httpx
from fastapi import FastAPI, HTTPException, Query

from contextlib import asynccontextmanager
from fastapi.concurrency import run_in_threadpool


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.storage import initialize_db

    await run_in_threadpool(initialize_db)

    yield


app = FastAPI(
    title="Aegis AI: Incident Diagnostics",
    version="1.0.0",
    lifespan=lifespan,
)

@app.get('/healthz')
async def healthz():
    return {'status': 'ok'}

@app.get('/investigate')
async def investigate(threshold_ms: float = Query(100.0, gt=0, allow_inf_nan=False)):
    url = os.environ.get('AEGIS_MANAGER_URL', 'http://localhost:8001').rstrip('/') + '/weights'
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict) or not payload:
            raise ValueError('missing backend telemetry')
        backends = []
        for name, info in sorted(payload.items()):
            if not isinstance(info, dict) or info.get('healthy') not in (0, 1, False, True):
                raise ValueError('invalid health telemetry')
            raw = info.get('ewma_ms')
            if raw is not None and (isinstance(raw, bool) or not isinstance(raw, (float, int)) or not math.isfinite(raw) or raw < 0):
                raise ValueError('invalid latency telemetry')
            backends.append({'name': name, 'healthy': bool(info['healthy']), 'ewma_ms': raw})
    except (httpx.HTTPError, ValueError, OverflowError) as exc:
        raise HTTPException(status_code=503, detail='Aegis telemetry unavailable or invalid') from exc
    findings = []
    for b in backends:
        if not b['healthy']:
            findings.append({'backend': b['name'], 'issue': 'unhealthy', 'evidence': 'manager healthy=0'})
        elif b['ewma_ms'] is None:
            findings.append({'backend': b['name'], 'issue': 'unknown_latency', 'evidence': 'EWMA missing'})
        elif b['ewma_ms'] > threshold_ms:
            findings.append({'backend': b['name'], 'issue': 'high_latency', 'evidence': f"EWMA {b['ewma_ms']} ms > {threshold_ms} ms"})
    unhealthy = sum(not b['healthy'] for b in backends)
    severity = ('critical' if unhealthy == len(backends) else 'high' if unhealthy else 'medium' if any(f['issue']=='high_latency' for f in findings) else 'unknown' if findings else 'none')
    return {'severity': severity, 'threshold_ms': threshold_ms, 'backends': backends, 'findings': findings, 'source': 'Aegis manager /weights', 'limitations': ['Current findings are based on a single live telemetry snapshot', 'Health and EWMA do not establish root cause'], 'actions_executed': []}




def deterministic_fallback(incident: dict) -> dict:
    """Return a grounded explanation without an AI provider."""

    from app.grounding import build_grounded_explanation

    explanation = build_grounded_explanation(
        incident,
        {"hypotheses": []},
    )

    explanation["summary"] = (
        f"Detected {len(incident['findings'])} finding(s). "
        f"Incident severity: {incident['severity']}. "
        "AI explanation unavailable; "
        "deterministic diagnostics provided."
    )

    checks = list(explanation["recommended_checks"])

    for finding in incident["findings"]:
        backend = finding["backend"]
        issue = finding["issue"]

        if issue == "high_latency":
            checks.extend([
                f"{backend}: Inspect CPU and memory utilization.",
                f"{backend}: Inspect request volume and queueing.",
                f"{backend}: Check downstream dependency latency.",
            ])

        elif issue == "unhealthy":
            checks.extend([
                f"{backend}: Review container logs and readiness.",
                f"{backend}: Check dependency connectivity.",
            ])

        elif issue == "unknown_latency":
            checks.extend([
                f"{backend}: Verify telemetry freshness.",
                f"{backend}: Inspect manager probe failures.",
            ])

    explanation["recommended_checks"] = list(
        dict.fromkeys(checks)
    )

    explanation["uncertainty"] = (
        "Root cause is unknown. "
        "AI hypothesis selection was unavailable. "
        "Current findings reflect a single live snapshot. "
        "Historical samples, when available, do not "
        "establish continuous degradation or causality."
    )

    explanation["grounding"] = {
        "observations": "deterministic",
        "hypothesis_selection": "unavailable",
        "hypothesis_wording": "not_applicable",
        "evidence_references_validated": True,
        "root_cause_confirmed": False,
    }

    return explanation


@app.get('/explain')
async def explain(threshold_ms: float = Query(100.0, gt=0, allow_inf_nan=False)):
    from app.ai import explain_with_gemini, DEFAULT_MODEL
    from fastapi.concurrency import run_in_threadpool

    incident = await investigate(threshold_ms=threshold_ms)
    from app.historical_context import enrich_incident

    incident = await run_in_threadpool(
        enrich_incident,
        incident,
    )

    from app.rag_service import select_runbooks
    runbooks, retrieval_metadata = await run_in_threadpool(
        select_runbooks, incident,
    )

    model = os.getenv("GEMINI_MODEL", DEFAULT_MODEL)

    ai_generated = True
    ai_status = "available"
    fallback_reason = None

    try:
        explanation = await run_in_threadpool(
            explain_with_gemini,
            incident,
            runbooks,
        )

    except HTTPException as exc:
        if exc.status_code not in (502, 503):
            raise

        explanation = deterministic_fallback(incident)
        ai_generated = False
        ai_status = "degraded"
        fallback_reason = exc.detail

    return {
        "incident": incident,
        "runbooks": [
            {
                "id": r["id"],
                "title": r["title"],
                "source": r["source"],
            }
            for r in runbooks
        ],
        "explanation": explanation,
        "model": model if ai_generated else None,
        "ai_generated": ai_generated,
        "ai_status": ai_status,
        "fallback_reason": fallback_reason,
        "review_required": True,
        "actions_executed": [],
        **({"retrieval": retrieval_metadata} if retrieval_metadata is not None else {}),
    }

@app.post("/collect", status_code=201)
async def collect(
    threshold_ms: float = Query(
        100.0,
        gt=0,
        allow_inf_nan=False,
    ),
):
    """Collect and persist a telemetry snapshot."""

    import logging
    import sqlite3

    from app.collector import collect_telemetry

    try:
        return await collect_telemetry(
            threshold_ms=threshold_ms
        )

    except (sqlite3.Error, OSError, RuntimeError) as exc:
        logging.getLogger(__name__).error(
            "Telemetry persistence failed: type=%s",
            type(exc).__name__,
        )

        raise HTTPException(
            status_code=503,
            detail="Telemetry persistence unavailable",
        ) from exc

from app.history import router as history_router

app.include_router(history_router)
