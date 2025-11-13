import streamlit as st
import pandas as pd
from typing import Dict, List, Any
from datetime import datetime, timedelta


from clients.linear.index import (
    create_linear_ticket,
    get_pending_linear_tickets,
    get_unstarted_linear_tickets,
    update_linear_ticket_title,
)
from clients.smartlead.index import get_campaigns
from common.utils import csv_to_json, upload_triage_data
from pages.va import deduplicate_linear_tickets


def assign_onboarding_and_scraping_tickets(
    assignments: Dict[str, List[str]],
    members: List[Dict[str, str]],
    onboarding_ticket_urls: List[str],
    scrape_ticket_urls: List[str],
) -> Dict[str, List[str]]:
    FULL_TIME_LEADS_QUOTA = 10  # 10 onboarding + scrape
    PART_TIME_LEADS_QUOTA = 5  # 5 onboarding + scrape
    SUPPORT_MEMBER_QUOTA = 2  # 1 onboarding + 1 scrape

    onboarding_index = 0
    scrape_index = 0

    st.write(
        f"Assigning onboarding and scrape tickets to **{len(members)}** members..."
    )
    progress_bar = st.progress(0)
    status_text = st.empty()

    for i, member in enumerate(members):
        name = member["name"]
        hours = member["hours"]
        role = member["role"]

        # Determine base quota
        if role == "support":
            base_quota = SUPPORT_MEMBER_QUOTA
        elif hours == "full-time":
            base_quota = FULL_TIME_LEADS_QUOTA
        else:
            base_quota = PART_TIME_LEADS_QUOTA

        existing_assignments = assignments.get(name, [])
        quota = base_quota - len(existing_assignments)
        assigned_to_member = 0

        while assigned_to_member < quota:
            ticket_assigned = False

            # Assign onboarding ticket first
            if onboarding_index < len(onboarding_ticket_urls):
                ticket_url = onboarding_ticket_urls[onboarding_index]
                assignments.setdefault(name, []).append(ticket_url)
                onboarding_index += 1
                assigned_to_member += 1
                ticket_assigned = True

                if assigned_to_member >= quota:
                    break

            # Then assign scrape ticket
            if scrape_index < len(scrape_ticket_urls):
                ticket_url = scrape_ticket_urls[scrape_index]
                assignments.setdefault(name, []).append(ticket_url)
                scrape_index += 1
                assigned_to_member += 1
                ticket_assigned = True

            # If nothing was assigned, avoid infinite loop
            if not ticket_assigned:
                break

        status_text.write(f"✅ Assigned {assigned_to_member} tickets to **{name}**")
        progress_bar.progress((i + 1) / len(members))

    st.success("🎉 All members have been assigned tickets.")
    return assignments


def assign_email_tickets(
    assignments: Dict[str, List[str]],
    members: List[Dict[str, str]],
    email_ticket_urls: List[str],
) -> Dict[str, List[str]]:
    EMAIL_MEMBER_QUOTA = 20  # Each member gets 20 email tickets

    st.write(f"📧 Assigning email tickets to **{len(members)}** members...")
    progress_bar = st.progress(0)
    status_text = st.empty()

    total_members = len(members)

    for i, member in enumerate(members):
        name = member["name"]

        if len(email_ticket_urls) > 0:
            # Take first 20 email tickets
            email_tickets_to_assign = email_ticket_urls[:EMAIL_MEMBER_QUOTA]

            # Add to member's existing assignments
            member_assignments = assignments.get(name, [])
            member_assignments.extend(email_tickets_to_assign)
            assignments[name] = member_assignments

            # Remove assigned tickets from pool
            email_ticket_urls = email_ticket_urls[EMAIL_MEMBER_QUOTA:]

            status_text.write(
                f"✅ Assigned {len(email_tickets_to_assign)} email tickets to **{name}**"
            )
        else:
            status_text.write(f"⚠️ No email tickets available to assign to **{name}**")

        progress_bar.progress((i + 1) / total_members)

    st.success("🎉 Email ticket assignment complete.")
    return assignments


def find_completed_campaigns_and_create_tickets() -> List[Dict[str, Any]]:
    pending_tickets = get_pending_linear_tickets()
    smartlead_campaigns = get_campaigns()
    conn = st.connection("postgresql", type="sql")
    query = """
SELECT
  slc.*,
  po.id AS "organizationId",
  po.name AS "organizationName",
  po.paused AS "organizationPaused"
FROM smart_lead_campaigns slc
LEFT JOIN platform_organizations po ON slc."platformOrganizationId" = po.id
"""
    campaigns = conn.query(query)
    active_cohesive_campaign_ids = [
        c["campaignId"]
        for c in campaigns
        if c.get("platformOrganization") and not c["platformOrganization"].get("paused")
    ]
    active_id_set = {str(cid) for cid in active_cohesive_campaign_ids}
    completed_campaigns = [
        c
        for c in smartlead_campaigns
        if c.get("status") == "COMPLETED" and str(c.get("id")) in active_id_set
    ]
    today_tag = datetime.now().strftime("%y_%m_%d")
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    completed_campaign_tickets = []
    for campaign in completed_campaigns:
        campaign_name = campaign.get("name")
        campaign_id = campaign.get("id")
        matching_ticket = None
        for t in pending_tickets:
            desc = t.get("description") or ""
            title = t.get("title") or ""
            if campaign_name in desc and "AUTOMATED" in title and "Scrape" in title:
                matching_ticket = t
                break
        if not matching_ticket:
            new_title = (
                f"[AUTOMATED | {today_tag} | COMPLETED CAMPAIGN]: "
                f"Scrape more leads for {campaign_name} by {tomorrow}"
            )
            description = (
                f"Campaign URL: "
                f"https://app.smartlead.ai/app/email-campaign/{campaign_id}/analytics"
            )

            new_ticket = create_linear_ticket(
                {
                    "title": new_title,
                    "description": description,
                }
            )
            completed_campaign_tickets.append(new_ticket)
            continue
        existing_title = matching_ticket.get("title", "")

        if "COMPLETED" in existing_title:
            completed_campaign_tickets.append(matching_ticket)
        else:
            updated_prefix = f"[AUTOMATED | {today_tag} | COMPLETED CAMPAIGN]:"
            import re

            updated_title = re.sub(
                r"^\[AUTOMATED \| \d{4}-\d{2}-\d{2}\]:", updated_prefix, existing_title
            )

            updated_issue = update_linear_ticket_title(
                issue_id=matching_ticket["id"], title=updated_title
            )

            if updated_issue:
                completed_campaign_tickets.append(updated_issue)

        completed_campaign_tickets.append(matching_ticket)

    return completed_campaign_tickets


def assign_completed_campaigns_tickets(
    assignments: Dict[str, List[str]],
    members: List[Dict[str, str]],
    completed_campaign_ticket_urls: List[str],
) -> Dict[str, List[str]]:
    COMPLETED_CAMPAIGN_MEMBER_QUOTA = (
        40  # Each member gets up to 40 completed campaign tickets
    )

    st.write(
        f"🎯 Assigning completed campaign tickets to **{len(members)}** members..."
    )
    progress_bar = st.progress(0)
    status_text = st.empty()

    total_members = len(members)

    for i, member in enumerate(members):
        name = member["name"]

        if len(completed_campaign_ticket_urls) > 0:
            # Take first 40 tickets
            tickets_to_assign = completed_campaign_ticket_urls[
                :COMPLETED_CAMPAIGN_MEMBER_QUOTA
            ]

            # Add to this member’s assignment list
            member_assignments = assignments.get(name, [])
            member_assignments.extend(tickets_to_assign)
            assignments[name] = member_assignments

            # Remove assigned tickets from pool
            completed_campaign_ticket_urls = completed_campaign_ticket_urls[
                COMPLETED_CAMPAIGN_MEMBER_QUOTA:
            ]

            status_text.write(
                f"✅ Assigned {len(tickets_to_assign)} completed campaign tickets to **{name}**"
            )
        else:
            status_text.write(
                f"⚠️ No completed campaign tickets left to assign to **{name}**"
            )

        progress_bar.progress((i + 1) / total_members)

    st.success("🎉 Completed campaign ticket assignment finished.")
    return assignments


def assign_tickets_to_team_members():
    st.title("Assign Tickets to Team Members")
    escalate_completed = st.checkbox(
        "Find completed campaigns and create tickets before assignment (optional)"
    )
    if escalate_completed:
        with st.spinner("Processing completed campaigns..."):
            completed_issues = find_completed_campaigns_and_create_tickets()
        st.success(
            f"Created/Found {len(completed_issues)} tickets for completed campaigns."
        )
    dedup = st.checkbox("Deduplicate existing tickets before assignment (optional)")
    if dedup:
        with st.spinner("Deduplicating Linear tickets..."):
            deduplicate_linear_tickets()
        st.success("Deduplication completed.")
    proceed_assignment = st.checkbox("Proceed with ticket assignment?")
    if not proceed_assignment:
        st.info("Ticket assignment cancelled.")
        return
    st.subheader("Upload Team Member File")
    team_file = st.file_uploader("Upload CSV/TSV", type=["csv", "tsv"])

    if not team_file:
        st.stop()

    team_raw = team_file.read().decode("utf-8")
    delimiter = "\t" if team_file.name.endswith(".tsv") else ","
    team_members = csv_to_json(team_raw, delimiter)
    st.subheader("Upload Existing Ticket Assignments (Optional)")
    existing_file = st.file_uploader(
        "Upload CSV/TSV of existing tickets", type=["csv", "tsv"]
    )
    existing_scrape = []
    existing_email = []
    existing_onboarding = []
    existing_completed = []
    if existing_file:
        existing_raw = existing_file.read().decode("utf-8")
        delimiter2 = "\t" if existing_file.name.endswith(".tsv") else ","
        existing_tickets = csv_to_json(existing_raw, delimiter2)
        for t in existing_tickets:
            title = t.get("Title", "")
            url = t.get("URL", "")
            if "purchase" in title.lower() or "email account" in title.lower():
                existing_email.append({"ticketTitle": title, "ticketUrl": url})
            elif "onboard" in title.lower():
                existing_onboarding.append({"ticketTitle": title, "ticketUrl": url})
            elif "completed" in title.upper():
                existing_completed.append({"ticketTitle": title, "ticketUrl": url})
            else:
                existing_scrape.append({"ticketTitle": title, "ticketUrl": url})
    st.write("Fetching pending Linear tickets...")
    pending = get_unstarted_linear_tickets()
    scrape_tickets = []
    email_tickets = []
    onboarding_tickets = []
    completed_tickets = []

    existing_all = (
        existing_scrape + existing_email + existing_onboarding + existing_completed
    )
    existing_urls = {e["ticketUrl"] for e in existing_all}

    for t in pending:
        if t["url"] in existing_urls:
            continue
        title = t["title"].lower()

        if "purchase" in title or "email account" in title:
            email_tickets.append(t)
        elif "onboard" in title:
            onboarding_tickets.append(t)
        elif "completed" in t["title"].upper():
            completed_tickets.append(t)
        else:
            scrape_tickets.append(t)

    def sort_tickets(arr):
        def pri(x):
            p = x.get("priority") or 0
            return 999 if p == 0 else p

        return sorted(arr, key=pri)

    sorted_scrape = sort_tickets(scrape_tickets)
    sorted_email = sort_tickets(email_tickets)
    sorted_onboarding = sort_tickets(onboarding_tickets)
    sorted_completed = sort_tickets(completed_tickets)

    email_members = []
    support_members = []
    lead_members = []
    completed_members = []

    for member in team_members:
        role = str(member.get("role", "")).lower()
        if role == "email":
            email_members.append(member)
        elif role == "support":
            support_members.append(member)
        elif role == "leads":
            lead_members.append(member)
        elif role == "completed_campaigns":
            completed_members.append(member)

    assignments = {}

    assignments = assign_onboarding_and_scraping_tickets(
        assignments=assignments,
        members=[
            {"name": m["name"], "hours": m["hours"], "role": m["role"]}
            for m in (support_members + lead_members)
        ],
        onboarding_ticket_urls=[t["ticketUrl"] for t in existing_onboarding],
        scrape_ticket_urls=[t["ticketUrl"] for t in existing_scrape],
    )

    assignments = assign_onboarding_and_scraping_tickets(
        assignments=assignments,
        members=[
            {"name": m["name"], "hours": m["hours"], "role": m["role"]}
            for m in (support_members + lead_members)
        ],
        onboarding_ticket_urls=[t["url"] for t in sorted_onboarding],
        scrape_ticket_urls=[t["url"] for t in sorted_scrape],
    )

    assignments = assign_email_tickets(
        assignments=assignments,
        members=[
            {"name": m["name"], "hours": m["hours"], "role": m["role"]}
            for m in email_members
        ],
        email_ticket_urls=[t["ticketUrl"] for t in existing_email],
    )

    assignments = assign_email_tickets(
        assignments=assignments,
        members=[
            {"name": m["name"], "hours": m["hours"], "role": m["role"]}
            for m in email_members
        ],
        email_ticket_urls=[t["url"] for t in sorted_email],
    )

    assignments = assign_completed_campaigns_tickets(
        assignments=assignments,
        members=[
            {"name": m["name"], "hours": m["hours"], "role": m["role"]}
            for m in completed_members
        ],
        completed_campaign_ticket_urls=[t["ticketUrl"] for t in existing_completed],
    )

    assignments = assign_completed_campaigns_tickets(
        assignments=assignments,
        members=[
            {"name": m["name"], "hours": m["hours"], "role": m["role"]}
            for m in completed_members
        ],
        completed_campaign_ticket_urls=[t["url"] for t in sorted_completed],
    )

    assignment_rows = []
    for member, urls in assignments.items():
        for url in urls:
            assignment_rows.append({"memberName": member, "ticketUrl": url})

    df_assignments = pd.DataFrame(assignment_rows)
    st.subheader("Preview of Assignments")
    st.dataframe(df_assignments)

    file_name = f"ticket_assignments_{datetime.datetime.now().strftime('%y_%m_%d')}.tsv"
    with st.spinner("Uploading assignments..."):
        blob_url = upload_triage_data(data=assignment_rows, fileName=file_name)

    st.success("Uploaded to Azure Blob Storage.")
    st.markdown(f"[View the file]({blob_url})")


assign_tickets_to_team_members()
