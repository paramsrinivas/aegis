"""Structured output contracts for incident agents."""

from pydantic import BaseModel, ConfigDict, Field


class HypothesisSelection(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
    )

    hypothesis_id: str
    backend: str
    evidence_ids: list[str] = Field(min_length=1)


class HypothesisOutput(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
    )

    hypotheses: list[HypothesisSelection] = Field(
        max_length=10
    )


def remove_additional_properties(schema):
    """Remove unsupported provider schema keywords."""

    if isinstance(schema, dict):
        schema.pop("additionalProperties", None)

        for value in schema.values():
            remove_additional_properties(value)

    elif isinstance(schema, list):
        for value in schema:
            remove_additional_properties(value)


class GeminiHypothesisSelection(BaseModel):
    """Preserve untrusted fields for downstream validation."""

    model_config = ConfigDict(
        extra="allow",
        strict=True,
        json_schema_extra=remove_additional_properties,
    )

    hypothesis_id: str
    backend: str
    evidence_ids: list[str] = Field(min_length=1)


class GeminiHypothesisOutput(BaseModel):
    """Provider-compatible schema without silent field removal."""

    model_config = ConfigDict(
        extra="allow",
        strict=True,
        json_schema_extra=remove_additional_properties,
    )

    hypotheses: list[GeminiHypothesisSelection] = Field(
        max_length=10
    )
