"""Tests for isolated, privacy-conscious traces."""

import asyncio
import json
import logging

import pytest

from app.observability import (
    diagnostic_trace,
    timed_stage,
    trace_id_var,
)


def events(caplog):
    return [
        json.loads(record.message)
        for record in caplog.records
        if record.name == "aegis.diagnostics"
    ]


def test_trace_created_and_reset():
    assert trace_id_var.get() is None

    with diagnostic_trace() as trace_id:
        assert len(trace_id) == 32
        assert trace_id_var.get() == trace_id

    assert trace_id_var.get() is None


def test_unique_trace_ids():
    with diagnostic_trace() as first:
        pass

    with diagnostic_trace() as second:
        pass

    assert first != second


def test_nested_trace_restores_parent():
    with diagnostic_trace() as outer:
        with diagnostic_trace() as inner:
            assert inner != outer

        assert trace_id_var.get() == outer


def test_successful_stage(caplog):
    caplog.set_level(logging.INFO)

    with diagnostic_trace() as trace_id:
        with timed_stage("retrieval"):
            pass

    event = events(caplog)[0]

    assert event["trace_id"] == trace_id
    assert event["stage"] == "retrieval"
    assert event["status"] == "success"
    assert event["duration_ms"] >= 0
    assert "error_type" not in event


def test_failed_stage_preserves_exception(caplog):
    with diagnostic_trace():
        with pytest.raises(RuntimeError):
            with timed_stage("hypothesis"):
                raise RuntimeError("provider failed")

    event = events(caplog)[0]

    assert event["status"] == "error"
    assert event["error_type"] == "RuntimeError"
    assert event["duration_ms"] >= 0


def test_exception_message_not_logged(caplog):
    secret = "sensitive-test-credential"

    with diagnostic_trace():
        with pytest.raises(ValueError):
            with timed_stage("grounding"):
                raise ValueError(secret)

    assert secret not in caplog.text
    assert events(caplog)[0]["error_type"] == "ValueError"


def test_concurrent_trace_isolation(caplog):
    caplog.set_level(logging.INFO)

    async def worker():
        with diagnostic_trace() as trace_id:
            await asyncio.sleep(0)

            with timed_stage("triage"):
                assert trace_id_var.get() == trace_id

            return trace_id

    async def run():
        return await asyncio.gather(
            worker(),
            worker(),
        )

    trace_ids = asyncio.run(run())

    assert len(set(trace_ids)) == 2

    assert {
        event["trace_id"]
        for event in events(caplog)
    } == set(trace_ids)


def test_cancelled_stage(caplog):
    async def run():
        with diagnostic_trace():
            with timed_stage("hypothesis"):
                raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run())

    event = events(caplog)[0]

    assert event["status"] == "error"
    assert event["error_type"] == "CancelledError"
    assert trace_id_var.get() is None


def test_thread_trace_propagation(caplog):
    caplog.set_level(logging.INFO)

    def worker():
        with timed_stage("retrieval"):
            return trace_id_var.get()

    async def run():
        with diagnostic_trace() as trace_id:
            observed = await asyncio.to_thread(worker)
            assert observed == trace_id
            return trace_id

    trace_id = asyncio.run(run())

    assert events(caplog)[0]["trace_id"] == trace_id


from app.observability import (
    classify_failure,
    emit_outcome,
)


class ProviderError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__("Sensitive provider response")


@pytest.mark.parametrize(
    "error,expected",
    [
        (ProviderError(503), "provider_unavailable"),
        (ProviderError(429), "provider_rate_limited"),
        (ProviderError(404), "provider_error"),
        (ProviderError(400), "provider_error"),
        (TimeoutError(), "timeout"),
        (ValueError(), "validation_error"),
        (RuntimeError(), "internal_error"),
    ],
)
def test_failure_classification(error, expected):
    assert classify_failure(error) == expected


def test_available_outcome(caplog):
    caplog.set_level(logging.INFO)

    with diagnostic_trace() as trace_id:
        emit_outcome("available")

    event = events(caplog)[0]

    assert event == {
        "event": "diagnostic_outcome",
        "trace_id": trace_id,
        "ai_status": "available",
        "fallback": False,
        "reason": None,
    }


def test_degraded_outcome(caplog):
    with diagnostic_trace() as trace_id:
        emit_outcome("degraded", "missing_api_key")

    event = events(caplog)[0]

    assert event["trace_id"] == trace_id
    assert event["ai_status"] == "degraded"
    assert event["fallback"] is True
    assert event["reason"] == "missing_api_key"


def test_outcome_rejects_untrusted_reason():
    with diagnostic_trace():
        with pytest.raises(ValueError):
            emit_outcome(
                "degraded",
                "sensitive-provider-response",
            )


def test_available_outcome_rejects_failure():
    with diagnostic_trace():
        with pytest.raises(ValueError):
            emit_outcome("available", "timeout")
