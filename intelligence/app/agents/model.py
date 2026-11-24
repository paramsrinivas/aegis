"""Instrument Gemini execution without modifying model output."""

from contextlib import aclosing

from google.adk.models.google_llm import Gemini

from app.observability import (
    timed_stage,
    emit_model_usage,
)


class ObservedGemini(Gemini):
    """Preserve Gemini behavior while recording execution metrics."""

    async def generate_content_async(
        self,
        llm_request,
        stream=False,
    ):
        usage = None

        with timed_stage("hypothesis"):
            try:
                async with aclosing(
                    super().generate_content_async(
                        llm_request,
                        stream=stream,
                    )
                ) as responses:
                    async for response in responses:
                        if response.usage_metadata is not None:
                            usage = response.usage_metadata

                        yield response
            finally:
                emit_model_usage(usage)
