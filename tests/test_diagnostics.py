
import asyncio
from unittest.mock import patch

import httpx
import pytest
from fastapi import HTTPException

from app.main import investigate


class MockResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


class MockClient:
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def get(self, url):
        if self.error:
            raise self.error

        return MockResponse(self.payload)


def run_investigation(payload, threshold=100.0):
    with patch(
        "app.main.httpx.AsyncClient",
        return_value=MockClient(payload=payload),
    ):
        return asyncio.run(investigate(threshold))


def test_normal_operation():
    result = run_investigation({
        "backend1": {"healthy": 1, "ewma_ms": 40},
        "backend2": {"healthy": 1, "ewma_ms": 60},
    })

    assert result["severity"] == "none"
    assert result["findings"] == []
    assert result["actions_executed"] == []


def test_high_latency():
    result = run_investigation({
        "backend1": {"healthy": 1, "ewma_ms": 145},
        "backend2": {"healthy": 1, "ewma_ms": 50},
    })

    assert result["severity"] == "medium"
    assert len(result["findings"]) == 1
    assert result["findings"][0]["issue"] == "high_latency"
    assert result["findings"][0]["backend"] == "backend1"


def test_threshold_boundary():
    result = run_investigation({
        "backend1": {"healthy": 1, "ewma_ms": 100},
    })

    assert result["severity"] == "none"
    assert result["findings"] == []


def test_custom_threshold():
    result = run_investigation({
        "backend1": {"healthy": 1, "ewma_ms": 75},
    }, threshold=50)

    assert result["severity"] == "medium"
    assert result["threshold_ms"] == 50


def test_single_unhealthy_backend():
    result = run_investigation({
        "backend1": {"healthy": 0, "ewma_ms": None},
        "backend2": {"healthy": 1, "ewma_ms": 50},
    })

    assert result["severity"] == "high"
    assert len(result["findings"]) == 1
    assert result["findings"][0]["issue"] == "unhealthy"


def test_all_backends_unhealthy():
    result = run_investigation({
        "backend1": {"healthy": 0, "ewma_ms": None},
        "backend2": {"healthy": 0, "ewma_ms": None},
    })

    assert result["severity"] == "critical"
    assert len(result["findings"]) == 2


def test_missing_latency():
    result = run_investigation({
        "backend1": {"healthy": 1, "ewma_ms": None},
    })

    assert result["severity"] == "unknown"
    assert result["findings"][0]["issue"] == "unknown_latency"


def test_zero_latency():
    result = run_investigation({
        "backend1": {"healthy": 1, "ewma_ms": 0},
    })

    assert result["severity"] == "none"
    assert result["findings"] == []


def test_mixed_incident_severity():
    result = run_investigation({
        "backend1": {"healthy": 0, "ewma_ms": None},
        "backend2": {"healthy": 1, "ewma_ms": 150},
        "backend3": {"healthy": 1, "ewma_ms": None},
    })

    assert result["severity"] == "high"

    assert {f["issue"] for f in result["findings"]} == {
        "unhealthy",
        "high_latency",
        "unknown_latency",
    }

    assert result["actions_executed"] == []


@pytest.mark.parametrize("payload", [
    {},
    [],
    None,
    {"backend1": None},
    {"backend1": {"healthy": 2, "ewma_ms": 50}},
    {"backend1": {"healthy": "yes", "ewma_ms": 50}},
    {"backend1": {"healthy": 1, "ewma_ms": -10}},
    {"backend1": {"healthy": 1, "ewma_ms": "fast"}},
    {"backend1": {"healthy": 1, "ewma_ms": True}},
    {"backend1": {"healthy": 1, "ewma_ms": float("nan")}},
    {"backend1": {"healthy": 1, "ewma_ms": float("inf")}},
])
def test_invalid_telemetry(payload):
    with pytest.raises(HTTPException) as error:
        run_investigation(payload)

    assert error.value.status_code == 503


@pytest.mark.parametrize("failure", [
    httpx.ConnectError("Simulated connection failure"),
    httpx.ReadTimeout("Simulated timeout"),
    httpx.HTTPStatusError(
        "Simulated HTTP failure",
        request=httpx.Request(
            "GET", "http://localhost:8001/weights"
        ),
        response=httpx.Response(500),
    ),
])
def test_manager_unavailable(failure):
    with patch(
        "app.main.httpx.AsyncClient",
        return_value=MockClient(error=failure),
    ):
        with pytest.raises(HTTPException) as error:
            asyncio.run(investigate(100.0))

    assert error.value.status_code == 503

