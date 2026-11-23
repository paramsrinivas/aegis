import pytest
from fastapi import HTTPException
from router import choose_backend

def test_never_selects_unhealthy_backend():
    weights = {
        "backend1": {"healthy": 0, "ewma_ms": 1},
        "backend2": {"healthy": 1, "ewma_ms": 20},
        "backend3": {"healthy": 0, "ewma_ms": 1},
    }
    assert all(choose_backend(weights) == "backend2" for _ in range(100))

def test_no_healthy_backend_returns_503():
    with pytest.raises(HTTPException) as exc:
        choose_backend({"backend1": {"healthy": 0, "ewma_ms": 20}})
    assert exc.value.status_code == 503

def test_missing_weights_fails_closed():
    with pytest.raises(HTTPException) as exc:
        choose_backend(None)
    assert exc.value.status_code == 503
