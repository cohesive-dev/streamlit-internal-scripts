import re
import time
import streamlit as st
from datetime import datetime

from clients.linear.index import get_pending_linear_tickets, remove_linear_ticket


def deduplicate_linear_tickets():
    st.title("Deduplicate Linear Tickets")

    st.write("Fetching pending Linear tickets...")
    issues = get_pending_linear_tickets()
    st.write(f"Found **{len(issues)}** issues to deduplicate.")

    title_map = {}  # { core_title: [issues] }

    # Group tickets by core title
    pattern = re.compile(
        r"^\[AUTOMATED \| \d{4}-\d{2}-\d{2}\]: (.+?) \d{4}-\d{2}-\d{2}$"
    )

    for issue in issues:
        title = issue["title"]
        match = pattern.match(title)
        if match:
            core_title = match.group(1)
            title_map.setdefault(core_title, []).append(issue)

    total_closed = 0
    groups = list(title_map.keys())

    st.write(f"Processing **{len(groups)}** groups of duplicated tickets...")

    progress = st.progress(0)
    status = st.empty()

    for idx, core_title in enumerate(groups, start=1):
        tickets = title_map[core_title]
        try:
            if len(tickets) > 1:
                tickets.sort(
                    key=lambda t: datetime.fromisoformat(
                        t["updatedAt"].replace("Z", "+00:00")
                    )
                )

                tickets_to_close = tickets[:-1]

                for t in tickets_to_close:
                    remove_linear_ticket(t["id"])
                    total_closed += 1

                status.write(
                    f"Closed **{len(tickets_to_close)}** duplicate tickets for: "
                    f"**{core_title}**"
                )
        except Exception as e:
            status.write(
                f"Error processing tickets for **{core_title}**: {str(e) or 'Unknown error'}"
            )
            continue

        progress.progress(idx / len(groups))
        time.sleep(10)

    st.success(f"Total tickets closed: **{total_closed}**")


deduplicate_linear_tickets()
