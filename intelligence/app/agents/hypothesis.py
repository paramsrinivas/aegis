"""Restricted ADK hypothesis selection agent."""

import os

from google.adk.agents import Agent
from google.genai import types

from app.ai import DEFAULT_MODEL, SYSTEM_RULES
from app.agents.schemas import (
    GeminiHypothesisOutput,
    HypothesisOutput,
)


def validate_raw_response(callback_context, llm_response):
    """Reject invalid model output before ADK normalizes it."""

    content = llm_response.content

    if content is None or not content.parts:
        raise ValueError("Missing hypothesis response")

    text_parts = []

    for part in content.parts:
        if getattr(part, "thought", False):
            continue

        if part.text is None:
            raise ValueError(
                "Unexpected non-text model output"
            )

        text_parts.append(part.text)

    if not text_parts:
        raise ValueError("Empty hypothesis response")

    raw = "".join(text_parts)

    HypothesisOutput.model_validate_json(raw)

    return None


def build_hypothesis_agent(
    model=None,
    before_model_callback=None,
):
    if model is None:
        model = os.getenv(
            "GEMINI_MODEL",
            DEFAULT_MODEL,
        )

    return Agent(
        name="hypothesis_agent",
        description=(
            "Selects permitted incident hypotheses "
            "for human investigation."
        ),
        model=model,
        instruction=SYSTEM_RULES,
        output_schema=GeminiHypothesisOutput,
        output_key="hypothesis_output",
        generate_content_config=types.GenerateContentConfig(
            temperature=0,
        ),
        mode="single_turn",
        tools=[],
        sub_agents=[],
        disallow_transfer_to_parent=True,
        disallow_transfer_to_peers=True,
        before_model_callback=before_model_callback,
        after_model_callback=validate_raw_response,
        timeout=20.0,
    )
