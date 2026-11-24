
"""REST API client for the Aegis AI dashboard."""

import os

import httpx


class APIError(Exception):
    """Raised when an Aegis AI API request fails."""


class AegisClient:


    def historical_backends(self):
        return self._request(
            "GET",
            "/historical-backends",
        )
    def __init__(self, base_url=None):
        self.base_url = (
            base_url
            or os.getenv(
                "AEGIS_AI_API_URL",
                "http://127.0.0.1:8010",
            )
        ).rstrip("/")

    def _request(
        self,
        method,
        path,
        params=None,
        timeout=10.0,
    ):
        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.request(
                    method,
                    f"{self.base_url}{path}",
                    params=params,
                )

                response.raise_for_status()

                result = response.json()

                if not isinstance(result, dict):
                    raise APIError(
                        "Unexpected API response format."
                    )

                return result

        except httpx.TimeoutException as exc:
            raise APIError(
                "The API request timed out."
            ) from exc

        except httpx.ConnectError as exc:
            raise APIError(
                "Cannot connect to the Aegis AI API."
            ) from exc

        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code

            raise APIError(
                f"API request failed with HTTP {status}."
            ) from exc

        except httpx.HTTPError as exc:
            raise APIError(
                "API communication failed."
            ) from exc

        except ValueError as exc:
            raise APIError(
                "The API returned invalid JSON."
            ) from exc

    def health(self):
        return self._request("GET", "/healthz")

    def investigate(self, threshold_ms=100.0):
        return self._request(
            "GET",
            "/investigate",
            params={"threshold_ms": threshold_ms},
        )

    def collect(self, threshold_ms=100.0):
        return self._request(
            "POST",
            "/collect",
            params={"threshold_ms": threshold_ms},
        )

    def snapshots(self, limit=100):
        return self._request(
            "GET",
            "/snapshots",
            params={"limit": limit},
        )

    def snapshot(self, snapshot_id):
        return self._request(
            "GET",
            f"/snapshots/{snapshot_id}",
        )

    def history(self, backend, limit=100):
        return self._request(
            "GET",
            f"/history/{backend}",
            params={"limit": limit},
        )

    def trends(
        self,
        backend,
        threshold_ms=100.0,
        limit=100,
    ):
        return self._request(
            "GET",
            f"/trends/{backend}",
            params={
                "threshold_ms": threshold_ms,
                "limit": limit,
            },
        )

    def incidents(self, status=None, limit=100):
        params = {"limit": limit}

        if status is not None:
            params["status"] = status

        return self._request(
            "GET",
            "/incidents",
            params=params,
        )

    def incident(self, incident_id):
        return self._request(
            "GET",
            f"/incidents/{incident_id}",
        )

    def explain(self, threshold_ms=100.0):
        return self._request(
            "GET",
            "/explain",
            params={"threshold_ms": threshold_ms},
            timeout=90.0,
        )
