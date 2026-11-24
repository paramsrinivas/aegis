"""Privacy-conscious structured diagnostic tracing."""

import json
import logging
import time

from contextlib import contextmanager
from contextvars import ContextVar
from uuid import uuid4


logger = logging.getLogger("aegis.diagnostics")


def configure_diagnostic_logging():
    """Enable structured diagnostic events on stderr."""

    if not any(
        getattr(handler, "_aegis_diagnostics", False)
        for handler in logger.handlers
    ):
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        handler._aegis_diagnostics = True
        logger.addHandler(handler)

    logger.setLevel(logging.INFO)
    logger.propagate = False


trace_id_var = ContextVar(
    "diagnostic_trace_id",
    default=None,
)

ALLOWED_STAGES = frozenset({
    "request",
    "workflow",
    "triage",
    "retrieval",
    "hypothesis",
    "grounding",
    "fallback",
})


@contextmanager
def diagnostic_trace():
    """Create an isolated trace for one invocation."""

    trace_id = uuid4().hex
    token = trace_id_var.set(trace_id)

    try:
        yield trace_id
    finally:
        trace_id_var.reset(token)


def emit_event(
    stage,
    status,
    duration_ms,
    error_type=None,
):
    """Emit only explicitly permitted trace fields."""

    if stage not in ALLOWED_STAGES:
        raise ValueError("Unknown diagnostic stage")

    if status not in {"success", "error"}:
        raise ValueError("Unknown diagnostic status")

    payload = {
        "event": "diagnostic_stage",
        "trace_id": trace_id_var.get(),
        "stage": stage,
        "status": status,
        "duration_ms": round(duration_ms, 3),
    }

    if error_type is not None:
        payload["error_type"] = error_type

    level = (
        logging.INFO
        if status == "success"
        else logging.WARNING
    )

    logger.log(
        level,
        json.dumps(payload, separators=(",", ":")),
    )


@contextmanager
def timed_stage(stage):
    """Measure stage execution, including failures."""

    started = time.perf_counter()

    try:
        yield
    except BaseException as exc:
        emit_event(
            stage=stage,
            status="error",
            duration_ms=(
                time.perf_counter() - started
            ) * 1000,
            error_type=type(exc).__name__,
        )
        raise
    else:
        emit_event(
            stage=stage,
            status="success",
            duration_ms=(
                time.perf_counter() - started
            ) * 1000,
        )


def classify_failure(exc):
    """Classify direct and explicitly wrapped failures."""

    seen = set()
    current = exc
    validation_error = False

    while current is not None and id(current) not in seen:
        seen.add(id(current))

        if isinstance(current, TimeoutError):
            return "timeout"

        code = getattr(current, "code", None)

        if code == 503:
            return "provider_unavailable"

        if code == 429:
            return "provider_rate_limited"

        if type(code) is int and 400 <= code <= 599:
            return "provider_error"

        if isinstance(current, ValueError):
            validation_error = True

        current = current.__cause__

    if validation_error:
        return "validation_error"

    return "internal_error"


ALLOWED_FAILURE_REASONS = frozenset({
    "missing_api_key",
    "provider_unavailable",
    "provider_rate_limited",
    "provider_error",
    "timeout",
    "validation_error",
    "internal_error",
})


def emit_outcome(status, reason=None):
    """Record the final AI outcome separately from timing."""

    if status not in {"available", "degraded"}:
        raise ValueError("Unknown diagnostic outcome")

    if status == "available" and reason is not None:
        raise ValueError("Available outcome cannot have a failure")

    if (
        status == "degraded"
        and reason not in ALLOWED_FAILURE_REASONS
    ):
        raise ValueError("Unknown failure reason")

    payload = {
        "event": "diagnostic_outcome",
        "trace_id": trace_id_var.get(),
        "ai_status": status,
        "fallback": status == "degraded",
        "reason": reason,
    }

    logger.log(
        logging.INFO
        if status == "available"
        else logging.WARNING,
        json.dumps(payload, separators=(",", ":")),
    )


def emit_model_usage(metadata):
    """Record only provider-reported token counts."""

    fields = {
        "input_tokens": "prompt_token_count",
        "output_tokens": "candidates_token_count",
        "thinking_tokens": "thoughts_token_count",
        "total_tokens": "total_token_count",
        "cached_tokens": "cached_content_token_count",
    }

    payload = {
        "event": "model_usage",
        "trace_id": trace_id_var.get(),
    }

    for name, attribute in fields.items():
        value = getattr(metadata, attribute, None)

        payload[name] = (
            value
            if type(value) is int and value >= 0
            else None
        )

    payload["usage_available"] = any(
        payload[name] is not None
        for name in fields
    )

    logger.info(
        json.dumps(payload, separators=(",", ":"))
    )


def emit_retrieval_metrics(runbooks, metadata):
    """Record retrieval metadata without document content."""

    allowed_modes = {
        "off",
        "semantic_coverage",
        "deterministic_fallback",
    }

    allowed_reasons = {
        None,
        "invalid_rag_mode",
        "no_eligible_tags",
        "rag_unavailable",
        "agent_workflow_failed",
    }

    metadata = metadata or {}
    mode = metadata.get("mode", "off")
    reason = metadata.get("reason")

    payload = {
        "event": "retrieval_metrics",
        "trace_id": trace_id_var.get(),
        "mode": mode if mode in allowed_modes else "unknown",
        "fallback": metadata.get("fallback") is True,
        "reason": (
            reason if reason in allowed_reasons
            else "unknown"
        ),
        "document_count": len(runbooks),
    }

    logger.info(
        json.dumps(payload, separators=(",", ":"))
    )
