"""Tests for provider-boundary observability."""

import asyncio
import json
import logging
from unittest.mock import patch

import pytest

from google.adk.models.google_llm import Gemini
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from app.agents.model import ObservedGemini
from app.observability import (
    diagnostic_trace,
    emit_model_usage,
    emit_retrieval_metrics,
    classify_failure,
)


def events(caplog, event_type):
    return [
        json.loads(record.message)
        for record in caplog.records
        if record.name == "aegis.diagnostics"
        and json.loads(record.message)["event"] == event_type
    ]


def test_model_usage_available(caplog):
    caplog.set_level(logging.INFO)

    metadata = types.GenerateContentResponseUsageMetadata(
        prompt_token_count=120,
        candidates_token_count=30,
        total_token_count=150,
    )

    with diagnostic_trace() as trace_id:
        emit_model_usage(metadata)

    event = events(caplog, "model_usage")[0]

    assert event["trace_id"] == trace_id
    assert event["input_tokens"] == 120
    assert event["output_tokens"] == 30
    assert event["total_tokens"] == 150
    assert event["thinking_tokens"] is None
    assert event["usage_available"] is True


def test_missing_usage_is_not_zero(caplog):
    caplog.set_level(logging.INFO)

    with diagnostic_trace():
        emit_model_usage(None)

    event = events(caplog, "model_usage")[0]

    assert event["usage_available"] is False
    assert event["input_tokens"] is None
    assert event["output_tokens"] is None
    assert event["total_tokens"] is None


def test_model_preserves_response(caplog):
    caplog.set_level(logging.INFO)

    response = LlmResponse(
        content=types.Content(
            role="model",
            parts=[types.Part(text="test-response")],
        ),
        usage_metadata=(
            types.GenerateContentResponseUsageMetadata(
                prompt_token_count=10,
                candidates_token_count=5,
                total_token_count=15,
            )
        ),
    )

    async def fake_generation(self, request, stream=False):
        yield response

    async def run():
        model = ObservedGemini(model="test-model")

        with diagnostic_trace() as trace_id:
            result = [
                item
                async for item in model.generate_content_async(None)
            ]

        return result, trace_id

    with patch.object(
        Gemini,
        "generate_content_async",
        fake_generation,
    ):
        result, trace_id = asyncio.run(run())

    assert len(result) == 1
    assert result[0] is response

    usage = events(caplog, "model_usage")[0]
    stage = events(caplog, "diagnostic_stage")[0]

    assert usage["total_tokens"] == 15
    assert usage["trace_id"] == trace_id
    assert stage["trace_id"] == trace_id
    assert stage["stage"] == "hypothesis"
    assert stage["status"] == "success"


def test_model_failure_preserved(caplog):
    caplog.set_level(logging.INFO)

    async def fake_generation(self, request, stream=False):
        raise RuntimeError("private-provider-detail")
        yield

    async def run():
        model = ObservedGemini(model="test-model")

        with diagnostic_trace():
            async for _ in model.generate_content_async(None):
                pass

    with patch.object(
        Gemini,
        "generate_content_async",
        fake_generation,
    ):
        with pytest.raises(RuntimeError):
            asyncio.run(run())

    stage = events(caplog, "diagnostic_stage")[0]
    usage = events(caplog, "model_usage")[0]

    assert stage["status"] == "error"
    assert stage["error_type"] == "RuntimeError"
    assert usage["usage_available"] is False
    assert "private-provider-detail" not in caplog.text


def test_retrieval_metrics(caplog):
    caplog.set_level(logging.INFO)

    with diagnostic_trace() as trace_id:
        emit_retrieval_metrics(
            [{"content": "private-document-content"}],
            {
                "mode": "semantic_coverage",
                "fallback": False,
                "reason": None,
            },
        )

    event = events(caplog, "retrieval_metrics")[0]

    assert event["trace_id"] == trace_id
    assert event["document_count"] == 1
    assert event["mode"] == "semantic_coverage"
    assert event["fallback"] is False
    assert "private-document-content" not in caplog.text


def test_retrieval_fallback_metrics(caplog):
    caplog.set_level(logging.INFO)

    with diagnostic_trace():
        emit_retrieval_metrics(
            [],
            {
                "mode": "deterministic_fallback",
                "fallback": True,
                "reason": "rag_unavailable",
            },
        )

    event = events(caplog, "retrieval_metrics")[0]

    assert event["fallback"] is True
    assert event["reason"] == "rag_unavailable"
    assert event["document_count"] == 0


def test_wrapped_provider_error():
    class RateLimited(Exception):
        code = 429

    try:
        try:
            raise RateLimited()
        except RateLimited as exc:
            raise RuntimeError("Wrapped failure") from exc
    except RuntimeError as exc:
        assert classify_failure(exc) == "provider_rate_limited"
