import asyncio
import os
from datetime import datetime
from io import BytesIO

from azure.storage.blob import ContentSettings
import pandas as pd
import streamlit as st

from clients.azure_blob_storage.index import get_or_create_blob_service_client

from clients.smartlead.index import (
    get_campaign_by_id,
    get_leads_by_campaign_id_with_pagination,
)
from clients.smartlead.internal.index import remove_multiple_leads_from_campaign
from common.utils import chunk_list, csv_to_json, get_gpt_answer

# ========================== Helpers ==========================


def upload_filtered_leads_to_blob(
    leads_to_remove: list[dict], campaign_label: str
) -> str:
    df = pd.DataFrame(leads_to_remove)
    tsv_buffer = BytesIO()
    df.to_csv(tsv_buffer, sep="\t", index=False)
    tsv_buffer.seek(0)

    blob_service_client = get_or_create_blob_service_client()
    container_name = os.environ.get("SMARTLEAD_TRIAGE_CONTAINER")
    container_client = blob_service_client.get_container_client(container_name)

    blob_name = (
        f"filtered-leads-{campaign_label}-{datetime.today().strftime('%Y-%m-%d')}.tsv"
    )
    blob_client = container_client.get_blob_client(blob_name)

    blob_client.upload_blob(
        tsv_buffer,
        overwrite=True,
        content_settings=ContentSettings(content_type="text/tab-separated-values"),
    )
    return blob_client.url


async def is_outside_whitelisted_area(location: str, whitelisted_areas: str) -> bool:
    if not location or not whitelisted_areas:
        return False
    system = (
        "You are a helpful assistant that filters addresses based on whitelisted areas. "
        "The whitelisted areas are:\n" + whitelisted_areas.replace(";", "\n")
    )
    prompt = (
        f"Is the address {location} located within any of the whitelisted areas? "
        f"You answer should strictly be 'yes' or 'no'"
    )
    ans = await asyncio.to_thread(get_gpt_answer, system, prompt)
    return (ans or "").strip().lower() == "no"


async def is_in_blocklisted_industry(
    industry: str, blocklisted_industries: str
) -> bool:
    if not industry or not blocklisted_industries:
        return False
    system = (
        "You are a helpful assistant that filters industries based on blocklisted industries:\n"
        + blocklisted_industries.replace(";", "\n")
    )
    prompt = (
        f"Does the industry {industry} match any of the blocklisted industries? "
        f"Answer strictly 'yes' or 'no'"
    )
    ans = await asyncio.to_thread(get_gpt_answer, system, prompt)
    return (ans or "").strip().lower() == "yes"


async def is_outside_whitelisted_industry(
    industry: str, whitelisted_industries: str
) -> bool:
    if not industry or not whitelisted_industries:
        return False
    system = (
        "You are a helpful assistant that filters industries based on whitelisted industries:\n"
        + whitelisted_industries.replace(";", "\n")
    )
    prompt = (
        f"Does the industry {industry} stay within any of the whitelisted industries? "
        f"Answer strictly 'yes' or 'no'"
    )
    ans = await asyncio.to_thread(get_gpt_answer, system, prompt, 0.2)
    return (ans or "").strip().lower() == "no"


async def process_leads(
    raw_leads: list[dict],
    *,
    blocklisted_industries: str,
    whitelisted_industries: str,
    whitelisted_areas: str,
) -> list[dict]:
    """Return the subset of leads to remove, based on location/industry rules."""
    leads_to_remove: list[dict] = []
    batches = list(chunk_list(raw_leads, 50))
    total_batches = len(batches)

    status_placeholder = st.empty()
    for batch_idx, batch in enumerate(batches, 1):
        status_placeholder.text(
            f"Processing batch {batch_idx}/{total_batches} ({len(batch)} leads)..."
        )

        async def check_one(lead: dict):
            loc = lead.get("Location")
            industry = lead.get("informalIndustry")
            if await is_outside_whitelisted_area(loc, whitelisted_areas):
                return lead
            if await is_in_blocklisted_industry(industry, blocklisted_industries):
                return lead
            if await is_outside_whitelisted_industry(industry, whitelisted_industries):
                return lead
            return None

        results = await asyncio.gather(*(check_one(lead) for lead in batch))
        filtered = [x for x in results if x is not None]
        leads_to_remove.extend(filtered)
        status_placeholder.text(
            f"Batch {batch_idx}/{total_batches} complete: {len(filtered)} leads filtered out"
        )

    status_placeholder.text(
        f"Processing complete: {len(leads_to_remove)} total leads to remove"
    )
    return leads_to_remove


# ========================== UI & State ==========================

st.title("Smartlead Lead Filter Tool")
st.subheader(
    "Filter your leads using GPT by blocklisted or whitelisted industries/areas"
)

# Session state defaults
ss = st.session_state
ss.setdefault("selected_org_id", None)
ss.setdefault("selected_campaign_id", None)
ss.setdefault("selected_campaign_name", "")
ss.setdefault("leads_to_remove", [])
ss.setdefault("lead_details", [])
ss.setdefault("filtered_blob_url", "")
ss.setdefault("removing", False)

# Connect to PostgreSQL once
conn = st.connection("postgresql", type="sql")

# Query campaigns with joined organization info
query = """
SELECT
  slc.*,
  po.id AS "organizationId",
  po.name AS "organizationName",
  po.paused AS "organizationPaused"
FROM smart_lead_campaigns slc
LEFT JOIN platform_organizations po ON slc."platformOrganizationId" = po.id
"""
campaigns = conn.query(query, ttl=0)

print([campaign["name"] for campaign in campaigns])

# Filter active orgs
active_orgs = campaigns[campaigns["organizationPaused"] == False]
unique_orgs = active_orgs.drop_duplicates(subset=["organizationId"])
org_options = unique_orgs.set_index("organizationId")["organizationName"].to_dict()

ss.selected_org_id = st.selectbox(
    "Select an active organization",
    options=list(org_options.keys()),
    index=(
        0
        if ss.get("selected_org_id") not in org_options
        else list(org_options.keys()).index(ss.selected_org_id)
    ),
    format_func=lambda org_id: org_options[org_id],
    key="org_select",
)

# Filter campaigns for the org
org_campaigns = campaigns[campaigns["organizationId"] == ss.selected_org_id]
campaign_details = []
for _, row in org_campaigns.iterrows():
    try:
        campaign_detail = get_campaign_by_id(int(row["campaignId"]))
        campaign_details.append(campaign_detail)
    except Exception as e:
        continue

campaign_options = {c.id: c.name for c in campaign_details}
campaign_ids = list(campaign_options.keys())

if not campaign_ids:
    st.info("No campaigns for this organization.")
    st.stop()

# Use previous selection if available
if ss.get("selected_campaign_id") in campaign_options:
    default_idx = campaign_ids.index(ss.selected_campaign_id)
else:
    default_idx = 0

ss.selected_campaign_id = st.selectbox(
    "Select a campaign",
    options=campaign_ids,
    index=default_idx,
    format_func=lambda cid: campaign_options[cid],
    key="campaign_select",
)
selected_campaign = next(
    (c for c in campaign_details if c.id == ss.selected_campaign_id), None
)
ss.selected_campaign_name = campaign_options.get(ss.selected_campaign_id, "")

uploaded_file = st.file_uploader(
    "Upload the lead CSV file", type="csv", key="lead_file"
)
if uploaded_file is None:
    st.stop()

raw_leads = csv_to_json(uploaded_file.read())

# Filters
blocklisted_industries = st.text_input(
    "Blocklisted industries (semicolon separated)", key="blocklisted"
)
whitelisted_industries = st.text_input(
    "Whitelisted industries (semicolon separated)", key="whitelisted_industries"
)
whitelisted_areas = st.text_input(
    "Whitelisted areas (semicolon separated)", key="whitelisted_areas"
)

# ========================== Actions ==========================

# 1) Filter & upload
if st.button("🚀 Filter and Upload Leads", key="filter_upload_btn"):
    with st.spinner("Filtering leads... please wait"):
        leads_to_remove = asyncio.run(
            process_leads(
                raw_leads,
                blocklisted_industries=blocklisted_industries,
                whitelisted_industries=whitelisted_industries,
                whitelisted_areas=whitelisted_areas,
            )
        )
        if not leads_to_remove:
            st.info("✅ No leads matched the filter criteria.")
            # Clear stale state
            ss.leads_to_remove = []
            ss.lead_details = []
            ss.filtered_blob_url = ""
            # No rerun needed
        else:
            url = upload_filtered_leads_to_blob(
                leads_to_remove, ss.selected_campaign_name
            )
            st.success(f"✅ Found {len(leads_to_remove)} leads to remove.")
            st.markdown(
                f"[📂 Review filtered leads from campaign **{ss.selected_campaign_name}**]({url})"
            )

            # Snapshot for next rerun
            ss.leads_to_remove = leads_to_remove
            ss.filtered_blob_url = url

            # Precompute campaign leads & mapping
            leads = get_leads_by_campaign_id_with_pagination(
                campaign_id=int(ss.selected_campaign_id)
            )
            # Match by email
            ss.lead_details = [
                {"leadId": lead.lead.id, "leadMappingId": lead.campaign_lead_map_id}
                for lead in leads
                if any(ltr.get("Email") == lead.lead.email for ltr in leads_to_remove)
            ]

    # Ensure the “Remove” CTA renders immediately with the computed state
    st.rerun()

# 2) Show removal CTA when we have data
if ss.lead_details:
    st.info(
        f"Ready to remove {len(ss.lead_details)} matched leads from **{ss.selected_campaign_name}**."
    )
    if ss.filtered_blob_url:
        st.markdown(
            f"[📂 Review filtered leads from campaign **{ss.selected_campaign_name}**]({ss.filtered_blob_url})"
        )

    if st.button(
        f"🚨 Remove {len(ss.lead_details)} matched leads from {ss.selected_campaign_name}",
        key="remove_btn",
    ):
        # Flip flag and rerun so spinner wraps the whole side-effect block
        ss.removing = True
        st.rerun()

# 3) Perform removal exactly once, with spinner
if ss.removing:
    with st.spinner("Removing leads... please wait"):
        try:
            remove_multiple_leads_from_campaign(
                smartlead_campaign_id=str(ss.selected_campaign_id),
                email_lead_ids=[ld["leadId"] for ld in ss.lead_details],
                email_lead_map_ids=[ld["leadMappingId"] for ld in ss.lead_details],
            )
        except Exception as e:
            st.error(
                f"❌ Failed to remove leads from campaign {ss.selected_campaign_name}: {e}"
            )
        else:
            st.success(
                f"✅ Removed {len(ss.lead_details)} leads from {ss.selected_campaign_name}."
            )
        finally:
            ss.removing = False
