import os
import math
import httpx
from fastapi import FastAPI, HTTPException, Query

app = FastAPI(title="Aegis AI: Incident Diagnostics", version="0.1.0")

@app.get('/healthz')
async def healthz():
    return {'status': 'ok'}

@app.get('/investigate')
async def investigate(threshold_ms: float = Query(100.0, gt=0)):
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
    except (httpx.HTTPError, ValueError) as exc:
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
    return {'severity': severity, 'threshold_ms': threshold_ms, 'backends': backends, 'findings': findings, 'source': 'Aegis manager /weights', 'limitations': ['Single snapshot; no historical trend', 'Health and EWMA do not establish root cause'], 'actions_executed': []}




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
        "A single telemetry snapshot does not establish "
        "persistence or causality."
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
async def explain(threshold_ms: float = Query(100.0, gt=0)):
    from app.knowledge import retrieve
    from app.ai import explain_with_gemini, DEFAULT_MODEL
    from fastapi.concurrency import run_in_threadpool

    incident = await investigate(threshold_ms=threshold_ms)
    runbooks = retrieve(incident["findings"])

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
    }

