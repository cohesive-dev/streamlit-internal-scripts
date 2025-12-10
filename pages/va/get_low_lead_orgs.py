import streamlit as st
import pandas as pd
import datetime
from collections import defaultdict

from clients.smartlead.index import get_campaign_top_level_analytics_for_date_range
from common.utils import get_or_create_blob_service_client, json_to_csv
from azure.storage.blob import ContentSettings


def get_organizations_with_low_leads():
    st.title("Scan Organizations for Low Leads")

    tenure_days = st.number_input(
        "Enter the number of days to scan for leads (e.g., 7)", min_value=1, value=7
    )
    number_of_leads = st.number_input(
        "Enter minimum number of leads for low-lead flag", min_value=0, value=10
    )

    if not st.button("Run Scan"):
        return

    st.write("Fetching campaigns...")
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
    campaigns = conn.query(query, ttl=0)
    campaigns = list(campaigns.to_dict(orient="records"))

    seven_days_ago = datetime.datetime.now() - datetime.timedelta(days=7)

    # Filter for active organizations + campaigns created > 7 days ago
    tenured_campaigns = [
        c
        for c in campaigns
        if not c["organizationPaused"] and c["smartLeadCreationDate"] < seven_days_ago
    ]

    st.write(f"Scanning {len(tenured_campaigns)} campaigns...")

    # Group campaigns by platformOrganizationId
    grouped = defaultdict(list)
    for c in tenured_campaigns:
        grouped[c["platformOrganizationId"]].append(c)

    start_date = (
        datetime.datetime(2024, 11, 16) - datetime.timedelta(days=tenure_days)
    ).strftime("%Y-%m-%d")
    end_date = datetime.datetime(2024, 11, 16).strftime("%Y-%m-%d")

    campaigns_with_low_leads = []
    file_name = (
        f"platforms_with_low_leads_{datetime.datetime.now().strftime('%y_%m_%d')}.tsv"
    )

    # Upload helper
    def upload_low_leads_data():
        blob_service_client = get_or_create_blob_service_client()
        container = blob_service_client.get_container_client(
            st.secrets["SMARTLEAD_TRIAGE_CONTAINER"]
        )
        blob = container.get_blob_client(file_name)

        tsv = json_to_csv(campaigns_with_low_leads, delimiter="\t")
        blob.upload_blob(
            tsv,
            overwrite=True,
            content_settings=ContentSettings(content_type="text/tab-separated-values"),
        )
        return blob.url

    progress = st.progress(0)
    status = st.empty()

    total = len(grouped)
    index = 0

    print(len(grouped))

    # Filter grouped to only include specific org_id
    grouped = {k: v for k, v in grouped.items() if k == "cmd6kycde042ycl0t09txu8c9"}

    print(len(grouped))

    for org_id, org_campaigns in grouped.items():
        org_name = org_campaigns[0]["organizationName"] if org_campaigns else "Unknown"

        statistics = {
            "ID": org_id,
            "platformOrganizationName": org_name,
            "leadCount": 0,
            "validCampaignCount": 0,
            "note": "",
        }

        try:
            for camp in org_campaigns:
                analytics = get_campaign_top_level_analytics_for_date_range(
                    camp["campaignId"],
                    start_date=start_date,
                    end_date=end_date,
                )

                if analytics.get("status") == "ACTIVE":
                    statistics["leadCount"] += int(
                        analytics.get("positive_reply_count", 0)
                    )
                    statistics["validCampaignCount"] += 1
        except Exception as e:
            statistics["note"] += f"Error fetching leads: {str(e)}"

        # Add if it's low-leads
        if (
            statistics["validCampaignCount"] > 0
            and statistics["leadCount"] <= number_of_leads
        ):
            campaigns_with_low_leads.append(statistics)
            status.write(
                f"⚠️ Found organization **{org_name}** with only **{statistics['leadCount']}** leads"
            )

        # Upload every 5 organizations
        if index % 5 == 0:
            blob_url = upload_low_leads_data()

        # Update progress bar
        progress.progress((index + 1) / total)
        index += 1

    # Final upload
    final_url = upload_low_leads_data()
    st.success(f"✅ Uploaded low leads data: {final_url}")


get_organizations_with_low_leads()
