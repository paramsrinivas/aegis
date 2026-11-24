
"""Persistent incident management dashboard."""

from datetime import datetime

import streamlit as st

from dashboard.api import APIError


def format_timestamp(value):
    if not value:
        return "Not available"

    try:
        timestamp = datetime.fromisoformat(value)

        return timestamp.strftime(
            "%d %b %Y, %H:%M:%S %Z"
        )

    except (ValueError, TypeError):
        return str(value)


def format_issue(issue):
    return issue.replace("_", " ").title()


def render_incident_details(client, incident):
    incident_id = incident["id"]

    st.subheader(f"Incident #{incident_id}")

    if incident["status"] == "open":
        st.warning("Open incident")
    else:
        st.success("Resolved incident")

    columns = st.columns(3)

    columns[0].metric(
        "Backend",
        incident["backend"],
    )

    columns[1].metric(
        "Issue",
        format_issue(incident["issue"]),
    )

    columns[2].metric(
        "Observations",
        incident["observation_count"],
    )

    st.caption(
        f"Incident threshold: "
        f"{incident['threshold_ms']:g} ms"
    )

    st.divider()

    st.subheader("Incident lifecycle")

    with st.container(border=True):
        st.markdown("**First detected**")

        st.write(
            format_timestamp(
                incident["first_seen_at"]
            )
        )

        st.caption(
            f"Snapshot "
            f"#{incident['first_snapshot_id']}"
        )

    with st.container(border=True):
        st.markdown("**Last observed issue**")

        st.write(
            format_timestamp(
                incident["last_seen_at"]
            )
        )

        st.caption(
            f"Snapshot "
            f"#{incident['last_snapshot_id']}"
        )

    with st.container(border=True):
        st.markdown("**Resolution**")

        if incident["status"] == "resolved":
            st.success(
                format_timestamp(
                    incident["resolved_at"]
                )
            )

            st.caption(
                f"Recovery snapshot "
                f"#{incident['resolved_snapshot_id']}"
            )

        else:
            st.info(
                "No confirmed recovery observation "
                "has been recorded."
            )

    st.divider()

    st.subheader("Latest incident evidence")

    st.code(
        incident["latest_evidence"],
        language=None,
    )

    with st.expander("Inspect supporting snapshots"):
        snapshot_ids = list(dict.fromkeys(
            snapshot_id
            for snapshot_id in [
                incident["first_snapshot_id"],
                incident["last_snapshot_id"],
                incident["resolved_snapshot_id"],
            ]
            if snapshot_id is not None
        ))

        selected_snapshot = st.selectbox(
            "Supporting snapshot",
            snapshot_ids,
            format_func=lambda value: (
                f"Snapshot #{value}"
            ),
            key=f"incident_snapshot_{incident_id}",
        )

        if st.button(
            "Load snapshot evidence",
            key=f"load_snapshot_{incident_id}",
        ):
            snapshot = client.snapshot(
                selected_snapshot
            )

            st.caption(
                format_timestamp(
                    snapshot["captured_at"]
                )
            )

            st.dataframe(
                snapshot["backends"],
                hide_index=True,
                width="stretch",
            )

            st.json(snapshot["findings"])

    with st.expander("Incident record"):
        st.json(incident)

    st.caption(
        "Incident status reflects stored observations. "
        "It does not establish continuous degradation "
        "or a confirmed root cause."
    )


def render_incidents_page(client):
    st.header("Incident Management")

    st.caption(
        "Inspect persistent incidents, supporting "
        "evidence and observed recovery."
    )

    try:
        result = client.incidents(limit=100)

        incidents = result["incidents"]

        open_count = sum(
            item["status"] == "open"
            for item in incidents
        )

        resolved_count = sum(
            item["status"] == "resolved"
            for item in incidents
        )

        columns = st.columns(3)

        columns[0].metric(
            "Retrieved incidents",
            len(incidents),
        )

        columns[1].metric(
            "Open incidents",
            open_count,
        )

        columns[2].metric(
            "Resolved incidents",
            resolved_count,
        )

        st.caption(
            "Counts cover the latest 100 "
            "retrieved incident records."
        )

        st.divider()

        status_filter = st.selectbox(
            "Incident status",
            ["All", "Open", "Resolved"],
            key="incident_status_filter",
        )

        filtered = [
            item
            for item in incidents
            if (
                status_filter == "All"
                or item["status"]
                == status_filter.lower()
            )
        ]

        if not filtered:
            st.info(
                "No incidents match the selected filter."
            )
            return

        rows = [
            {
                "ID": item["id"],
                "Backend": item["backend"],
                "Issue": format_issue(item["issue"]),
                "Status": item["status"].upper(),
                "Threshold (ms)": item["threshold_ms"],
                "Observations": item["observation_count"],
                "Last observed": format_timestamp(
                    item["last_seen_at"]
                ),
            }
            for item in filtered
        ]

        st.dataframe(
            rows,
            hide_index=True,
            width="stretch",
        )

        incident_map = {
            item["id"]: item
            for item in filtered
        }

        selected_id = st.selectbox(
            "Inspect incident",
            list(incident_map),
            format_func=lambda value: (
                f"#{value} — "
                f"{incident_map[value]['backend']} — "
                f"{format_issue(incident_map[value]['issue'])}"
            ),
            key="selected_incident",
        )

        incident = client.incident(selected_id)

        st.divider()

        render_incident_details(
            client,
            incident,
        )

    except APIError as exc:
        st.error(str(exc))
