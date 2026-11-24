"""Bounded ADK incident diagnostic workflow."""

import asyncio
import json
from copy import deepcopy

from google.adk.workflow import Workflow, FunctionNode
from google.adk.runners import InMemoryRunner
from google.genai import types

from app.agents.triage import prepare_triage
from app.agents.retrieval import retrieve_context
from app.agents.hypothesis import build_hypothesis_agent
from app.agents.validation import validate_selection
from app.observability import timed_stage


WORKFLOW_TIMEOUT_SECONDS = 40.0


async def run_diagnostic_workflow(
    incident: dict,
    model=None,
    before_model_callback=None,
) -> dict:
    """Execute an isolated diagnostic workflow."""

    snapshot = deepcopy(incident)
    stages = {}

    def triage():
        with timed_stage("triage"):
            stages["triage"] = prepare_triage(snapshot)
            return stages["triage"]

    async def retrieval():
        with timed_stage("retrieval"):
            stages["retrieval"] = await asyncio.to_thread(
                retrieve_context,
                snapshot,
            )
            return stages["retrieval"]

    async def prepare_model_request(context, llm_request):
        reasoning_context = {
            **stages["triage"],
            "runbooks": stages["retrieval"]["runbooks"],
        }

        llm_request.contents = [
            types.Content(
                role="user",
                parts=[
                    types.Part(
                        text=json.dumps(
                            reasoning_context,
                            ensure_ascii=False,
                        )
                    )
                ],
            )
        ]

        if before_model_callback is not None:
            result = before_model_callback(
                context,
                llm_request,
            )

            if asyncio.iscoroutine(result):
                result = await result

            return result

        return None

    triage_node = FunctionNode(
        name="triage",
        func=triage,
    )

    retrieval_node = FunctionNode(
        name="retrieval",
        func=retrieval,
        timeout=15.0,
    )

    agent = build_hypothesis_agent(
        model=model,
        before_model_callback=prepare_model_request,
    )

    def grounding(hypothesis_output):
        with timed_stage("grounding"):
            if isinstance(hypothesis_output, str):
                hypothesis_output = json.loads(
                    hypothesis_output
                )

            stages["explanation"] = validate_selection(
                snapshot,
                hypothesis_output,
            )

            return stages["explanation"]

    grounding_node = FunctionNode(
        name="grounding",
        func=grounding,
    )

    workflow = Workflow(
        name="aegis_diagnostic_workflow",
        edges=[
            ("START", triage_node),
            (triage_node, retrieval_node),
            (retrieval_node, agent),
            (agent, grounding_node),
        ],
        max_concurrency=1,
    )

    runner = InMemoryRunner(
        node=workflow,
        app_name="aegis_diagnostics",
    )

    with timed_stage("workflow"):
        async with asyncio.timeout(
            WORKFLOW_TIMEOUT_SECONDS
        ):
            session = await runner.session_service.create_session(
                app_name="aegis_diagnostics",
                user_id="incident-investigator",
            )

            async for event in runner.run_async(
                user_id="incident-investigator",
                session_id=session.id,
                new_message=types.Content(
                    role="user",
                    parts=[
                        types.Part(
                            text="Investigate the supplied incident."
                        )
                    ],
                ),
            ):
                pass

    if "explanation" not in stages:
        raise RuntimeError(
            "Workflow did not complete grounding"
        )

    return {
        "explanation": stages["explanation"],
        "runbooks": stages["retrieval"]["runbooks"],
        "retrieval": stages["retrieval"]["retrieval"],
        "review_required": True,
        "actions_executed": [],
    }
