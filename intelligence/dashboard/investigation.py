
"""Grounded AI investigation dashboard."""

from datetime import datetime, timezone

import streamlit as st

from dashboard.api import APIError


def render_provider_status(result):
    columns = st.columns(3)

    columns[0].metric(
        "AI provider",
        result["ai_status"].title(),
    )

    columns[1].metric(
        "Analysis mode",
        "AI-assisted"
        if result["ai_generated"]
        else "Deterministic",
    )

    columns[2].metric(
        "Actions executed",
        len(result["actions_executed"]),
    )

    if result["ai_generated"]:
        st.success(
            "Grounded AI investigation completed."
        )

        st.caption(
            f"Model: {result['model']}"
        )

    else:
        st.warning(
            "AI provider unavailable. "
            "Deterministic diagnostics remain available."
        )

        if result.get("fallback_reason"):
            st.caption(result["fallback_reason"])


def render_observations(explanation):
    st.subheader("Telemetry-derived observations")

    st.caption(
        "Generated deterministically from "
        "available telemetry and evidence."
    )

    for observation in explanation["observations"]:
        st.write(f"- {observation}")


def render_hypotheses(explanation):
    st.subheader("Potential explanations")

    st.caption(
        "Unconfirmed hypotheses selected from "
        "the approved hypothesis catalogue."
    )

    hypotheses = explanation["hypothesis_details"]

    if not hypotheses:
        st.info(
            "No AI-selected hypotheses available."
        )
        return

    for hypothesis in hypotheses:
        with st.container(border=True):
            st.markdown(
                f"**{hypothesis['statement']}**"
            )

            st.warning("Unconfirmed hypothesis")

            st.caption(
                f"Backend: {hypothesis['backend']}"
            )

            st.caption(
                "Evidence references: "
                + ", ".join(
                    hypothesis["evidence_ids"]
                )
            )

            st.markdown("**Recommended check**")

            st.write(
                hypothesis["recommended_check"]
            )


def render_evidence(explanation):
    st.subheader("Evidence explorer")

    evidence = explanation["evidence"]

    st.caption(
        f"{len(evidence)} registered evidence items."
    )

    kinds = sorted({
        item["kind"]
        for item in evidence
    })

    selected_kind = st.selectbox(
        "Evidence type",
        ["All"] + kinds,
        key="investigation_evidence_kind",
    )

    filtered = [
        item
        for item in evidence
        if (
            selected_kind == "All"
            or item["kind"] == selected_kind
        )
    ]

    rows = [
        {
            "ID": item["id"],
            "Type": item["kind"],
            "Backend": item["backend"] or "Global",
            "Observation": item["statement"],
        }
        for item in filtered
    ]

    st.dataframe(
        rows,
        hide_index=True,
        width="stretch",
    )

    if not filtered:
        return

    evidence_map = {
        item["id"]: item
        for item in filtered
    }

    selected_id = st.selectbox(
        "Inspect evidence",
        list(evidence_map),
        key="investigation_evidence_id",
    )

    selected = evidence_map[selected_id]

    with st.container(border=True):
        st.markdown(
            f"**Evidence {selected_id}**"
        )

        st.write(selected["statement"])

        st.json(selected)

        if selected["kind"] == "historical_observation":
            st.info(
                "Historical context only. "
                "Not proof of current conditions "
                "or causality."
            )


def render_investigation_page(client, threshold):
    st.header("AI Investigation")

    st.caption(
        "Evidence-grounded incident triage "
        "with human oversight."
    )

    st.info(
        "Investigations are read-only. "
        "Potential causes require independent "
        "verification and human review."
    )

    if st.button(
        "Run AI investigation",
        type="primary",
        width="stretch",
        key="run_ai_investigation",
    ):
        st.session_state.pop(
            "investigation_result",
            None,
        )

        try:
            with st.spinner(
                "Analyzing telemetry, retrieving runbooks "
                "and validating AI hypotheses..."
            ):
                result = client.explain(threshold)

            st.session_state[
                "investigation_result"
            ] = {
                "result": result,
                "threshold": threshold,
                "generated_at": datetime.now(
                    timezone.utc
                ).isoformat(),
            }

        except APIError as exc:
            st.error(str(exc))

    saved = st.session_state.get(
        "investigation_result"
    )

    if saved is None:
        st.caption(
            "Run an investigation to generate "
            "an incident assessment."
        )
        return

    if saved["threshold"] != threshold:
        st.warning(
            "The selected threshold has changed. "
            "Run a new investigation to update "
            "the assessment."
        )

    result = saved["result"]
    incident = result["incident"]
    explanation = result["explanation"]

    st.caption(
        f"Investigation completed: "
        f"{saved['generated_at']}"
    )

    st.caption(
        f"Investigation threshold: "
        f"{saved['threshold']:g} ms. "
        "Results reflect the investigation snapshot, "
        "not continuously updated telemetry."
    )

    render_provider_status(result)

    st.divider()

    st.subheader("Incident assessment")

    st.metric(
        "Investigated severity",
        incident["severity"].upper(),
    )

    st.write(explanation["summary"])

    st.divider()

    render_observations(explanation)

    st.divider()

    render_hypotheses(explanation)

    st.divider()

    st.subheader("Recommended diagnostic checks")

    for check in explanation["recommended_checks"]:
        st.write(f"- {check}")

    st.divider()

    render_evidence(explanation)

    st.divider()

    st.subheader("Historical context")

    st.caption(
        f"Status: {incident.get('historical_status', 'unknown')}"
    )

    for history in incident.get(
        "historical_context",
        [],
    ):
        with st.expander(
            f"Historical context — {history['backend']}"
        ):
            st.json(history)

    st.subheader("Retrieved runbooks")

    runbooks = result.get("runbooks", [])

    if not runbooks:
        st.info("No relevant runbooks retrieved.")

    for runbook in runbooks:
        with st.expander(
            runbook.get("title", "Runbook")
        ):
            st.json(runbook)

    st.divider()

    st.subheader("Grounding and safety")

    grounding = explanation["grounding"]

    if grounding["evidence_references_validated"]:
        st.success(
            "Evidence references validated."
        )

    if not grounding["root_cause_confirmed"]:
        st.warning(
            "Root cause remains unconfirmed."
        )

    if result["review_required"]:
        st.info("Human review required.")

    st.write(explanation["uncertainty"])

    with st.expander("Grounding metadata"):
        st.json(grounding)

    with st.expander("Complete investigation response"):
        st.json(result)
