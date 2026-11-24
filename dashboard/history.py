
"""Historical analytics dashboard section."""

import streamlit as st

from dashboard.api import APIError
from dashboard.charts import (
    render_history_chart,
    render_trend_metrics,
    render_trend_summary,
)


def render_history_page(client, threshold):
    st.header("Historical Analytics")

    st.caption(
        "Analyze stored telemetry and observed "
        "performance patterns."
    )

    try:
        discovery = client.historical_backends()
        backend_names = discovery["backends"]

        if not backend_names:
            st.info(
                "No stored telemetry. Collect a "
                "snapshot using the sidebar."
            )
            return

        columns = st.columns(2)

        backend = columns[0].selectbox(
            "Backend",
            sorted(backend_names),
            key="historical_backend",
        )

        limit = columns[1].selectbox(
            "Maximum observations",
            [10, 25, 50, 100],
            index=3,
            key="historical_limit",
        )

        with st.spinner("Loading historical telemetry..."):
            history = client.history(
                backend,
                limit=limit,
            )

            trends = client.trends(
                backend,
                threshold_ms=threshold,
                limit=limit,
            )

        render_trend_metrics(trends)

        st.divider()

        render_history_chart(
            history["samples"],
            threshold,
        )

        st.divider()

        render_trend_summary(trends)

        st.divider()

        with st.expander("Raw historical telemetry"):
            st.dataframe(
                history["samples"],
                width="stretch",
                hide_index=True,
            )

        st.caption(
            f"Analysis threshold: {threshold:g} ms. "
            f"Maximum observations: {limit}."
        )

    except APIError as exc:
        st.error(str(exc))
