
"""Aegis AI incident intelligence dashboard."""

import streamlit as st

from dashboard.api import AegisClient, APIError
from dashboard.history import render_history_page
from dashboard.incidents import render_incidents_page
from dashboard.investigation import render_investigation_page
from dashboard.components import (
    render_severity,
    render_metrics,
    render_backend_cards,
    render_latency_chart,
    render_findings,
)


st.set_page_config(
    page_title="Aegis AI",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

client = AegisClient()

st.title("Aegis AI")

st.caption(
    "Enterprise Incident Intelligence Platform"
)


with st.sidebar:
    st.header("Aegis AI")
    st.caption("Incident intelligence workspace")

    threshold = st.number_input(
        "Latency threshold (ms)",
        min_value=1.0,
        max_value=10000.0,
        value=100.0,
        step=10.0,
    )

    st.divider()

    st.subheader("System connection")

    try:
        health = client.health()

        if health.get("status") == "ok":
            st.success("Aegis AI API connected")
        else:
            st.warning("Unexpected API health response")

    except APIError as exc:
        st.error(str(exc))

    st.caption(f"API: {client.base_url}")

    st.divider()

    st.subheader("Telemetry controls")

    st.button(
        "Refresh diagnostics",
        width="stretch",
    )

    if st.button(
        "Collect telemetry snapshot",
        width="stretch",
        type="primary",
    ):
        try:
            with st.spinner("Collecting telemetry..."):
                result = client.collect(threshold)

            snapshot = result["snapshot"]

            st.success(
                f"Snapshot #{snapshot['id']} stored"
            )

        except APIError as exc:
            st.error(str(exc))

    st.caption(
        "Collection stores observations locally. "
        "It does not modify infrastructure."
    )

    st.divider()

    st.caption("Read-only infrastructure diagnostics")
    st.caption("Human review required")


st.subheader("Incident Intelligence Workspace")

overview, history, incidents, investigation = st.tabs([
    "Infrastructure Overview",
    "Historical Analytics",
    "Incident Management",
    "AI Investigation",
])


with overview:
    try:
        with st.spinner("Fetching live diagnostics..."):
            incident = client.investigate(threshold)

        render_metrics(incident)

        render_severity(
            incident["severity"]
        )

        st.divider()

        render_backend_cards(incident)

        st.divider()

        render_latency_chart(incident)

        st.divider()

        render_findings(incident)

        st.caption(
            f"Source: {incident['source']}"
        )

    except APIError as exc:
        st.error(str(exc))

        st.info(
            "Verify that the FastAPI service and "
            "Aegis infrastructure are running."
        )


with history:
    render_history_page(client, threshold)


with incidents:
    render_incidents_page(client)


with investigation:
    render_investigation_page(client, threshold)
