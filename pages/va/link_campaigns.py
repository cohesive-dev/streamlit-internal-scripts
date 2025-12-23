import streamlit as st
from dateutil import parser
from clients.smartlead.index import get_campaign_by_id
from sqlalchemy import text


conn = st.connection("postgresql", type="sql")


def get_platform_orgs():
    return conn.query(
        """
        SELECT id, name, domain
        FROM platform_organizations
        WHERE paused = false
        ORDER BY name
        """,
        ttl=0,
    )


def upsert_smartlead_campaign(
    campaign_id: str,
    platform_organization_id: str,
):
    # 1. Fetch campaign from SmartLead
    smartlead_campaign = get_campaign_by_id(int(campaign_id))

    if not smartlead_campaign or not smartlead_campaign.created_at:
        raise RuntimeError(f"SmartLead campaign with ID {campaign_id} not found.")

    smartlead_creation_date = parser.isoparse(smartlead_campaign.created_at)

    # 2. Prisma-style UPSERT
    with conn.session as s:
        s.execute(
            text(
                """
            INSERT INTO smart_lead_campaigns (
                id,
                "campaignId",
                "platformOrganizationId",
                "smartLeadCreationDate",
                "createdAt",
                "updatedAt"
            )
            VALUES (
                gen_random_uuid(),
                :campaign_id,
                :platform_organization_id,
                :smartlead_creation_date,
                NOW(),
                NOW()
            )
            ON CONFLICT ("campaignId")
            DO UPDATE SET
                "platformOrganizationId" = EXCLUDED."platformOrganizationId",
                "smartLeadCreationDate"  = EXCLUDED."smartLeadCreationDate",
                "updatedAt"              = NOW()
            """
            ),
            params={
                "campaign_id": campaign_id,
                "platform_organization_id": platform_organization_id,
                "smartlead_creation_date": smartlead_creation_date,
            },
        )
        s.commit()


st.title("Link SmartLead Campaign to Platform Organization")

# Step 1: Load orgs
orgs_df = get_platform_orgs()

if orgs_df.empty:
    st.warning("No active Platform Organizations found.")
    st.stop()

org_label_to_id = {
    f"{row['name']} ({row['domain']})": row["id"] for _, row in orgs_df.iterrows()
}

# Step 2: Select org
selected_org_label = st.selectbox(
    "Select Platform Organization",
    options=list(org_label_to_id.keys()),
)

# Step 3: Input SmartLead campaign IDs (comma-separated)
campaign_ids_input = st.text_input(
    "SmartLead Campaign IDs (comma-separated)",
    placeholder="e.g. 123456, 789012, 345678",
)

# Step 4: Action
if st.button("Link Campaign(s)", type="primary"):
    if not campaign_ids_input.strip():
        st.error("SmartLead Campaign ID(s) are required.")
    else:
        # Parse comma-separated IDs
        campaign_ids = [
            cid.strip() for cid in campaign_ids_input.split(",") if cid.strip()
        ]

        if not campaign_ids:
            st.error("Please provide at least one valid Campaign ID.")
        else:
            success_count = 0
            error_count = 0

            progress_bar = st.progress(0)
            status_text = st.empty()

            for idx, campaign_id in enumerate(campaign_ids):
                try:
                    status_text.text(f"Processing campaign {campaign_id}...")
                    upsert_smartlead_campaign(
                        campaign_id=campaign_id,
                        platform_organization_id=org_label_to_id[selected_org_label],
                    )
                    success_count += 1
                except Exception as e:
                    error_count += 1
                    st.error(f"Failed to link campaign `{campaign_id}`: {str(e)}")

                progress_bar.progress((idx + 1) / len(campaign_ids))

            status_text.empty()
            progress_bar.empty()

            if success_count > 0:
                st.success(
                    f"Successfully linked {success_count} campaign(s) to `{selected_org_label}`"
                )
            if error_count > 0:
                st.warning(f"{error_count} campaign(s) failed to link.")
