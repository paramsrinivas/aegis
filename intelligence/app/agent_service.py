"""Safe integration of ADK diagnostics into the API."""

import logging
import os

from fastapi.concurrency import run_in_threadpool
from app.observability import (
    diagnostic_trace,
    timed_stage,
    classify_failure,
    emit_outcome,
)

from app.ai import DEFAULT_MODEL
from app.grounding import build_grounded_explanation
from app.knowledge import retrieve


logger = logging.getLogger(__name__)


async def explain_with_adk(incident: dict) -> dict:
    """Run ADK diagnostics with deterministic fallback."""

    with diagnostic_trace():
        with timed_stage("request"):
            return await _explain_with_adk_traced(incident)


async def _explain_with_adk_traced(incident: dict) -> dict:
    """Execute the existing ADK service within its trace."""

    model = os.getenv("GEMINI_MODEL", DEFAULT_MODEL)
    failure_reason = None

    try:
        if not os.getenv("GEMINI_API_KEY", "").strip():
            failure_reason = "missing_api_key"
            raise RuntimeError("Gemini API key missing")

        from app.agents.workflow import (
            run_diagnostic_workflow,
        )

        from google import genai
        from google.genai import types
        from app.agents.model import ObservedGemini

        client = genai.Client(
            api_key=os.environ["GEMINI_API_KEY"].strip(),
            vertexai=False,
            http_options=types.HttpOptions(
                timeout=15000,
                retry_options=types.HttpRetryOptions(
                    attempts=1,
                ),
            ),
        )

        try:
            adk_model = ObservedGemini(
                model=model,
                client=client,
            )

            result = await run_diagnostic_workflow(
                incident,
                model=adk_model,
            )
        finally:
            try:
                await client.aio.aclose()
            finally:
                client.close()

        emit_outcome("available")

        return {
            **result,
            "model": model,
            "ai_generated": True,
            "ai_status": "available",
            "fallback_reason": None,
            "agent": {
                "mode": "adk",
                "fallback": False,
            },
        }

    except Exception as exc:
        failure_reason = (
            failure_reason or classify_failure(exc)
        )

        logger.warning(
            "ADK workflow failed: type=%s",
            type(exc).__name__,
        )

        with timed_stage("fallback"):
            runbooks = await run_in_threadpool(
                retrieve,
                incident["findings"],
            )

            explanation = build_grounded_explanation(
                incident,
                {"hypotheses": []},
            )

        explanation["grounding"].update({
            "hypothesis_selection": "unavailable",
            "hypothesis_wording": "not_applicable",
        })

        emit_outcome("degraded", failure_reason)

        return {
            "explanation": explanation,
            "runbooks": runbooks,
            "retrieval": {
                "mode": "deterministic_fallback",
                "fallback": True,
                "reason": "agent_workflow_failed",
            },
            "model": None,
            "ai_generated": False,
            "ai_status": "degraded",
            "fallback_reason": "ADK workflow unavailable",
            "review_required": True,
            "actions_executed": [],
            "agent": {
                "mode": "adk",
                "fallback": True,
            },
        }
