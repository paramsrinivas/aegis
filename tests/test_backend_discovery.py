
"""Tests for efficient historical backend discovery."""

from unittest.mock import patch

import sqlite3

from fastapi.testclient import TestClient

from app.main import app
from app.storage import (
    list_historical_backends,
    save_snapshot,
)
from dashboard.api import AegisClient


def make_snapshot(names):
    return {
        "threshold_ms": 100.0,
        "severity": "none",
        "source": "synthetic test telemetry",
        "backends": [
            {
                "name": name,
                "healthy": True,
                "ewma_ms": 45.0,
            }
            for name in names
        ],
        "findings": [],
    }


def test_empty_backend_discovery():
    assert list_historical_backends() == []


def test_single_backend_discovery():
    save_snapshot(
        make_snapshot(["backend1"])
    )

    assert list_historical_backends() == [
        "backend1"
    ]


def test_sorted_backend_discovery():
    save_snapshot(
        make_snapshot([
            "backend3",
            "backend1",
            "backend2",
        ])
    )

    assert list_historical_backends() == [
        "backend1",
        "backend2",
        "backend3",
    ]


def test_backend_discovery_deduplicates():
    for _ in range(5):
        save_snapshot(
            make_snapshot([
                "backend1",
                "backend2",
            ])
        )

    assert list_historical_backends() == [
        "backend1",
        "backend2",
    ]


def test_historical_backend_retained():
    save_snapshot(
        make_snapshot([
            "retired-backend",
            "backend1",
        ])
    )

    save_snapshot(
        make_snapshot(["backend1"])
    )

    assert list_historical_backends() == [
        "backend1",
        "retired-backend",
    ]


def test_empty_discovery_endpoint():
    with TestClient(app) as client:
        response = client.get(
            "/historical-backends"
        )

    assert response.status_code == 200

    assert response.json() == {
        "count": 0,
        "backends": [],
    }


def test_populated_discovery_endpoint():
    save_snapshot(
        make_snapshot([
            "backend2",
            "backend1",
        ])
    )

    with TestClient(app) as client:
        response = client.get(
            "/historical-backends"
        )

    assert response.status_code == 200

    assert response.json() == {
        "count": 2,
        "backends": [
            "backend1",
            "backend2",
        ],
    }


def test_discovery_storage_failure():
    with TestClient(app) as client:
        with patch(
            "app.storage.list_historical_backends",
            side_effect=sqlite3.OperationalError(
                "Simulated storage failure"
            ),
        ):
            response = client.get(
                "/historical-backends"
            )

    assert response.status_code == 503

    assert response.json()["detail"] == (
        "Historical storage unavailable"
    )


def test_dashboard_discovery_request():
    client = AegisClient(
        "http://test-api:8010"
    )

    expected = {
        "count": 1,
        "backends": ["backend1"],
    }

    with patch.object(
        client,
        "_request",
        return_value=expected,
    ) as request:
        assert (
            client.historical_backends()
            == expected
        )

    request.assert_called_once_with(
        "GET",
        "/historical-backends",
    )
