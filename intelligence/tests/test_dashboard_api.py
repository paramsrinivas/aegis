
"""Automated tests for the dashboard REST API client."""

from unittest.mock import patch

import httpx
import pytest

from dashboard.api import AegisClient, APIError


@pytest.fixture
def client():
    return AegisClient("http://test-api:8010")


@pytest.fixture
def transport():
    with patch("dashboard.api.httpx.Client") as mocked:
        session = mocked.return_value.__enter__.return_value
        yield mocked, session


def make_response(status=200, payload=None):
    return httpx.Response(
        status,
        json=payload if payload is not None else {"status": "ok"},
        request=httpx.Request(
            "GET", "http://test-api:8010"
        ),
    )


@pytest.mark.parametrize(
    "method,args,verb,path,params,timeout",
    [
        (
            "health", (), "GET",
            "/healthz", None, 10.0,
        ),
        (
            "investigate", (150,), "GET",
            "/investigate",
            {"threshold_ms": 150}, 10.0,
        ),
        (
            "collect", (125,), "POST",
            "/collect",
            {"threshold_ms": 125}, 10.0,
        ),
        (
            "snapshots", (25,), "GET",
            "/snapshots", {"limit": 25}, 10.0,
        ),
        (
            "snapshot", (4,), "GET",
            "/snapshots/4", None, 10.0,
        ),
        (
            "history", ("backend2", 50), "GET",
            "/history/backend2",
            {"limit": 50}, 10.0,
        ),
        (
            "trends", ("backend2", 120, 25), "GET",
            "/trends/backend2",
            {"threshold_ms": 120, "limit": 25},
            10.0,
        ),
        (
            "incidents", (), "GET",
            "/incidents", {"limit": 100}, 10.0,
        ),
        (
            "incidents", ("open", 25), "GET",
            "/incidents",
            {"status": "open", "limit": 25},
            10.0,
        ),
        (
            "incident", (1,), "GET",
            "/incidents/1", None, 10.0,
        ),
        (
            "explain", (100,), "GET",
            "/explain",
            {"threshold_ms": 100}, 90.0,
        ),
    ],
)
def test_endpoint_requests(
    client, transport, method, args,
    verb, path, params, timeout,
):
    mocked, session = transport

    session.request.return_value = make_response()

    result = getattr(client, method)(*args)

    assert result == {"status": "ok"}

    mocked.assert_called_once_with(
        timeout=timeout
    )

    session.request.assert_called_once_with(
        verb,
        f"http://test-api:8010{path}",
        params=params,
    )


def test_explicit_base_url():
    client = AegisClient(
        "http://example.test:8010/"
    )

    assert client.base_url == (
        "http://example.test:8010"
    )


def test_environment_base_url(monkeypatch):
    monkeypatch.setenv(
        "AEGIS_AI_API_URL",
        "http://configured-api:8010/",
    )

    assert AegisClient().base_url == (
        "http://configured-api:8010"
    )


def test_default_base_url(monkeypatch):
    monkeypatch.delenv(
        "AEGIS_AI_API_URL",
        raising=False,
    )

    assert AegisClient().base_url == (
        "http://127.0.0.1:8010"
    )


def test_explicit_url_overrides_environment(monkeypatch):
    monkeypatch.setenv(
        "AEGIS_AI_API_URL",
        "http://environment-api:8010",
    )

    assert AegisClient(
        "http://explicit-api:8010"
    ).base_url == "http://explicit-api:8010"


@pytest.mark.parametrize(
    "exception,message",
    [
        (
            httpx.ReadTimeout("timeout"),
            "timed out",
        ),
        (
            httpx.ConnectTimeout("timeout"),
            "timed out",
        ),
        (
            httpx.ConnectError("connection refused"),
            "Cannot connect",
        ),
        (
            httpx.ReadError("read failed"),
            "communication failed",
        ),
    ],
)
def test_transport_errors(
    client, transport, exception, message
):
    _, session = transport

    session.request.side_effect = exception

    with pytest.raises(APIError, match=message):
        client.health()


@pytest.mark.parametrize(
    "status",
    [400, 404, 422, 500, 502, 503, 504],
)
def test_http_status_errors(
    client, transport, status
):
    _, session = transport

    session.request.return_value = make_response(
        status=status
    )

    with pytest.raises(
        APIError,
        match=f"HTTP {status}",
    ):
        client.health()


def test_invalid_json(client, transport):
    _, session = transport

    session.request.return_value = httpx.Response(
        200,
        content=b"not valid JSON",
        request=httpx.Request(
            "GET", "http://test-api:8010"
        ),
    )

    with pytest.raises(
        APIError,
        match="invalid JSON",
    ):
        client.health()


@pytest.mark.parametrize(
    "payload",
    [
        [],
        ["unexpected"],
        "unexpected",
        123,
        True,
    ],
)
def test_invalid_response_format(
    client, transport, payload
):
    _, session = transport

    session.request.return_value = make_response(
        payload=payload
    )

    with pytest.raises(
        APIError,
        match="Unexpected API response format",
    ):
        client.health()


def test_successful_collection(client, transport):
    _, session = transport

    payload = {
        "status": "collected",
        "snapshot": {"id": 5},
        "actions_executed": [],
    }

    session.request.return_value = make_response(
        status=201,
        payload=payload,
    )

    assert client.collect() == payload


def test_provider_fallback_response(client, transport):
    _, session = transport

    payload = {
        "ai_generated": False,
        "ai_status": "degraded",
        "model": None,
        "review_required": True,
        "actions_executed": [],
    }

    session.request.return_value = make_response(
        payload=payload
    )

    assert client.explain() == payload
