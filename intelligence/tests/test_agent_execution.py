"""Runtime tests for ADK hypothesis selection."""

import asyncio
import json

from google.adk.models.llm_response import LlmResponse
from google.adk.runners import InMemoryRunner
from google.adk.workflow import Workflow
from google.genai import types

from app.agents.hypothesis import build_hypothesis_agent
from app.agents.schemas import HypothesisOutput


def execute_agent(payload):
    calls = []

    def mock_model(callback_context, llm_request):
        calls.append(llm_request)

        return LlmResponse(
            content=types.Content(
                role="model",
                parts=[
                    types.Part(text=json.dumps(payload))
                ],
            ),
        )

    async def run():
        agent = build_hypothesis_agent(
            before_model_callback=mock_model,
        )

        workflow = Workflow(
            name="aegis_agent_workflow",
            edges=[("START", agent)],
            max_concurrency=1,
        )

        runner = InMemoryRunner(
            node=workflow,
            app_name="aegis_agent_test",
        )

        session = await runner.session_service.create_session(
            app_name="aegis_agent_test",
            user_id="test-user",
        )

        async for event in runner.run_async(
            user_id="test-user",
            session_id=session.id,
            new_message=types.Content(
                role="user",
                parts=[
                    types.Part(
                        text="Select permitted hypotheses."
                    )
                ],
            ),
        ):
            pass

        updated = await runner.session_service.get_session(
            app_name="aegis_agent_test",
            user_id="test-user",
            session_id=session.id,
        )

        return updated.state.get("hypothesis_output")

    output = asyncio.run(run())

    assert len(calls) == 1

    if isinstance(output, str):
        output = json.loads(output)

    return HypothesisOutput.model_validate(
        output
    ).model_dump()


def test_agent_returns_empty_selection():
    payload = {"hypotheses": []}

    assert execute_agent(payload) == payload


def test_agent_returns_structured_selection():
    payload = {
        "hypotheses": [{
            "hypothesis_id": "resource_contention",
            "backend": "backend1",
            "evidence_ids": ["E004"],
        }]
    }

    assert execute_agent(payload) == payload
