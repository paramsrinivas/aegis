
"""Historical telemetry visualizations."""

import plotly.graph_objects as go
import streamlit as st


def render_history_chart(samples, threshold):
    st.subheader("Historical latency")

    if not samples:
        st.info("No historical observations available.")
        return

    ordered = sorted(
        samples,
        key=lambda item: (
            item["captured_at"],
            item["snapshot_id"],
        ),
    )

    figure = go.Figure()

    figure.add_trace(
        go.Scatter(
            x=[
                item["captured_at"]
                for item in ordered
            ],
            y=[
                item["ewma_ms"]
                if item["healthy"]
                else None
                for item in ordered
            ],
            mode="lines+markers",
            name="EWMA latency",
            line=dict(
                color="#38BDF8",
                width=3,
            ),
            marker=dict(
                size=9,
                color=[
                    "#F59E0B"
                    if (
                        item["healthy"]
                        and item["ewma_ms"] is not None
                        and item["ewma_ms"] > threshold
                    )
                    else "#38BDF8"
                    for item in ordered
                ],
            ),
            customdata=[
                item["snapshot_id"]
                for item in ordered
            ],
            hovertemplate=(
                "Snapshot #%{customdata}<br>"
                "Time: %{x}<br>"
                "EWMA: %{y:.2f} ms"
                "<extra></extra>"
            ),
            connectgaps=False,
        )
    )

    figure.add_hline(
        y=threshold,
        line_dash="dash",
        line_color="#F59E0B",
        annotation_text=(
            f"Analysis threshold: {threshold:g} ms"
        ),
    )

    figure.update_layout(
        height=420,
        margin=dict(l=20, r=20, t=40, b=20),
        xaxis_title="Observation time (UTC)",
        yaxis_title="EWMA latency (ms)",
        hovermode="closest",
        showlegend=True,
    )

    figure.update_xaxes(type="date")

    st.plotly_chart(
        figure,
        width="stretch",
    )

    st.caption(
        "Markers represent stored observations. "
        "Connecting lines do not establish continuous "
        "latency measurements between observations."
    )


def render_trend_metrics(trends):
    latency = trends["latency"]

    def format_ms(value):
        if value is None:
            return "Unavailable"

        return f"{value:.2f} ms"

    def format_percent(value):
        if value is None:
            return "Unavailable"

        return f"{value:.1f}%"

    columns = st.columns(4)

    columns[0].metric(
        "Stored observations",
        trends["sample_count"],
    )

    columns[1].metric(
        "Minimum EWMA",
        format_ms(latency["minimum_ms"]),
    )

    columns[2].metric(
        "Average EWMA",
        format_ms(latency["average_ms"]),
    )

    columns[3].metric(
        "Maximum EWMA",
        format_ms(latency["maximum_ms"]),
    )

    columns = st.columns(4)

    columns[0].metric(
        "Threshold violations",
        trends["threshold_violations"],
    )

    columns[1].metric(
        "Observed violation rate",
        format_percent(
            trends["violation_rate_percent"]
        ),
    )

    columns[2].metric(
        "Valid latency samples",
        trends["valid_latency_samples"],
    )

    columns[3].metric(
        "Healthy observation rate",
        format_percent(
            trends["health_rate_percent"]
        ),
    )


def render_trend_summary(trends):
    st.subheader("Historical assessment")

    patterns = {
        "repeated_threshold_violation": (
            "warning",
            "Repeated threshold violations",
        ),
        "intermittent_threshold_violation": (
            "warning",
            "Intermittent threshold violations",
        ),
        "no_observed_threshold_violation": (
            "success",
            "No observed threshold violations",
        ),
        "insufficient_data": (
            "info",
            "Insufficient historical data",
        ),
    }

    level, message = patterns.get(
        trends["pattern"],
        ("info", "Unknown historical pattern"),
    )

    getattr(st, level)(message)

    for statement in trends["evidence"]:
        st.write(f"- {statement}")

    if trends["first_observed_at"]:
        st.caption(
            f"First observation: "
            f"{trends['first_observed_at']}"
        )

        st.caption(
            f"Last observation: "
            f"{trends['last_observed_at']}"
        )

    with st.expander("Historical analysis limitations"):
        for limitation in trends["limitations"]:
            st.write(f"- {limitation}")

        st.caption(
            "Root cause remains unconfirmed."
        )
