
"""Gemini incident explanation with bounded retries and safe error handling."""

import json
import logging
import os
import time

from fastapi import HTTPException


logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-3.1-flash-lite"
MAX_ATTEMPTS = 3
REQUEST_TIMEOUT_MS = 15000
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


SYSTEM_RULES = """
You are an incident-analysis assistant.

Use ONLY the supplied telemetry and runbooks.

Never invent observations, trends, metrics, actions performed,
or confirmed root causes.

Separate measured observations from hypotheses.

Every hypothesis must be explicitly tentative.
Use wording such as "may", "might", or "could".
Never present a suspected cause as an established fact.

Say explicitly when the root cause is unknown.

Return ONLY a JSON object with these fields:

summary (string)
observations (list of strings)
hypotheses (list of strings)
recommended_checks (list of strings)
uncertainty (string)

Recommendations are for human review.
Never claim to execute them.
"""


def validate_response(parsed: dict) -> dict:
    """Validate the structure of the generated explanation."""

    expected = {
        "summary": str,
        "observations": list,
        "hypotheses": list,
        "recommended_checks": list,
        "uncertainty": str,
    }

    if not isinstance(parsed, dict):
        raise ValueError("Response must be a JSON object")

    for key, expected_type in expected.items():
        if not isinstance(parsed.get(key), expected_type):
            raise ValueError(f"Invalid response field: {key}")

    for key in (
        "observations",
        "hypotheses",
        "recommended_checks",
    ):
        if not all(
            isinstance(item, str) and item.strip()
            for item in parsed[key]
        ):
            raise ValueError(f"Invalid list field: {key}")

    if not parsed["summary"].strip():
        raise ValueError("Empty summary")

    if not parsed["uncertainty"].strip():
        raise ValueError("Empty uncertainty")

    return {key: parsed[key] for key in expected}


def explain_with_gemini(
    incident: dict,
    runbooks: list[dict],
) -> dict:
    """Generate an explanation without executing infrastructure actions."""

    key = os.getenv("GEMINI_API_KEY", "").strip()

    if not key:
        raise HTTPException(
            status_code=503,
            detail="GEMINI_API_KEY is not configured",
        )

    model = os.getenv("GEMINI_MODEL", DEFAULT_MODEL)

    try:
        from google import genai
        from google.genai import types

        with genai.Client(
            api_key=key,
            http_options=types.HttpOptions(
                timeout=REQUEST_TIMEOUT_MS,
                retry_options=types.HttpRetryOptions(
                    attempts=1,
                ),
            ),
        ) as client:

            context = {
                "incident": incident,
                "runbooks": runbooks,
            }

            config = types.GenerateContentConfig(
                system_instruction=SYSTEM_RULES,
                response_mime_type="application/json",
                temperature=0,
            )

            for attempt in range(1, MAX_ATTEMPTS + 1):
                try:
                    response = client.models.generate_content(
                        model=model,
                        contents=json.dumps(
                            context,
                            ensure_ascii=False,
                        ),
                        config=config,
                    )

                    parsed = json.loads(response.text or "")
                    return validate_response(parsed)

                except Exception as exc:
                    status = getattr(exc, "code", None)

                    logger.warning(
                        "Gemini attempt %s/%s failed: "
                        "type=%s status=%s",
                        attempt,
                        MAX_ATTEMPTS,
                        type(exc).__name__,
                        status,
                    )

                    retryable = status in RETRYABLE_STATUS_CODES

                    if retryable and attempt < MAX_ATTEMPTS:
                        delay = 2 ** (attempt - 1)
                        time.sleep(delay)
                        continue

                    if retryable:
                        raise HTTPException(
                            status_code=503,
                            detail="Gemini temporarily unavailable",
                        ) from exc

                    raise HTTPException(
                        status_code=502,
                        detail="Gemini explanation unavailable or invalid",
                    ) from exc

    except HTTPException:
        raise

    except Exception as exc:
        logger.error(
            "Gemini initialization failed: type=%s",
            type(exc).__name__,
        )

        raise HTTPException(
            status_code=502,
            detail="Gemini explanation unavailable or invalid",
        ) from exc

