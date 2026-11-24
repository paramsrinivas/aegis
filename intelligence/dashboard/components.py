
"""Reusable infrastructure dashboard components."""

import plotly.graph_objects as go
import streamlit as st


def render_severity(severity):
    messages = {
        "none": ("success", "No active findings"),
        "unknown": ("warning", "Telemetry incomplete"),
        "medium": ("warning", "Medium severity incident"),
        "high": ("error", "High severity incident"),
        "critical": ("error", "Critical severity incident"),
    }

    level, message = messages.get(
        severity,
        ("warning", "Unknown severity"),
    )

    getattr(st, level)(message)


def render_metrics(incident):
    backends = incident["backends"]

    healthy = sum(
        backend["healthy"]
        for backend in backends
    )

    elevated = sum(
        finding["issue"] == "high_latency"
        for finding in incident["findings"]
    )

    columns = st.columns(4)

    columns[0].metric(
        "Total backends",
        len(backends),
    )

    columns[1].metric(
        "Healthy backends",
        f"{healthy}/{len(backends)}",
    )

    columns[2].metric(
        "Elevated latency",
        elevated,
    )

    columns[3].metric(
        "Severity",
        incident["severity"].upper(),
    )


def render_backend_cards(incident):
    st.subheader("Backend status")

    threshold = incident["threshold_ms"]
    backends = incident["backends"]

    for start in range(0, len(backends), 3):
        batch = backends[start:start + 3]
        columns = st.columns(len(batch))

        for column, backend in zip(columns, batch):
            with column:
                with st.container(border=True):
                    st.markdown(
                        f"**{backend['name']}**"
                    )

                    latency = backend["ewma_ms"]

                    if not backend["healthy"]:
                        st.error("Unhealthy")

                    elif latency is None:
                        st.warning("Missing telemetry")

                    elif latency > threshold:
                        st.warning("Elevated latency")

                    else:
                        st.success("Healthy")

                    st.metric(
                        "EWMA latency",
                        (
                            f"{latency:.2f} ms"
                            if latency is not None
                            else "Unavailable"
                        ),
                    )

                    st.caption(
                        f"Threshold: {threshold:g} ms"
                    )


def render_latency_chart(incident):
    st.subheader("Backend latency comparison")

    threshold = incident["threshold_ms"]

    backends = [
        backend
        for backend in incident["backends"]
        if backend["ewma_ms"] is not None
    ]

    if not backends:
        st.info("No latency measurements available.")
        return

    colors = []

    for backend in backends:
        if not backend["healthy"]:
            colors.append("#EF4444")
        elif backend["ewma_ms"] > threshold:
            colors.append("#F59E0B")
        else:
            colors.append("#10B981")

    figure = go.Figure(
        go.Bar(
            x=[
                backend["name"]
                for backend in backends
            ],
            y=[
                backend["ewma_ms"]
                for backend in backends
            ],
            marker_color=colors,
            text=[
                f"{backend['ewma_ms']:.2f} ms"
                for backend in backends
            ],
            textposition="auto",
        )
    )

    figure.add_hline(
        y=threshold,
        line_dash="dash",
        line_color="#F59E0B",
        annotation_text=f"Threshold: {threshold:g} ms",
    )

    figure.update_layout(
        height=350,
        margin=dict(l=20, r=20, t=40, b=20),
        xaxis_title="Backend",
        yaxis_title="EWMA latency (ms)",
        showlegend=False,
    )

    st.plotly_chart(
        figure,
        width="stretch",
    )

    st.caption(
        "EWMA is a smoothed latency measurement, "
        "not an individual request duration."
    )


def render_findings(incident):
    st.subheader("Diagnostic findings")

    findings = incident["findings"]

    if not findings:
        st.success(
            "No findings at the selected threshold."
        )
        return

    for finding in findings:
        with st.container(border=True):
            st.markdown(
                f"**{finding['backend']}**"
            )

            st.write(
                finding["issue"]
                .replace("_", " ")
                .title()
            )

            st.code(
                finding["evidence"],
                language=None,
            )

    with st.expander("Diagnostic limitations"):
        for limitation in incident["limitations"]:
            st.write(f"- {limitation}")

        st.caption(
            "No infrastructure actions were executed."
        )
