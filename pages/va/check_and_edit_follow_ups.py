import streamlit as st
import pandas as pd
from sqlalchemy import text
from clients.smartlead.index import get_campaigns as get_smartlead_campaigns

st.title("Check & Edit Auto Follow-Up Jobs")

conn = st.connection("postgresql", type="sql")
ss = st.session_state
ss.setdefault("job_results", None)
ss.setdefault("last_campaign_id", None)
ss.setdefault("last_select_all", False)

# ========================== Step 1: Select Org ==========================

orgs_df = conn.query(
    """
    SELECT id, name
    FROM platform_organizations
    WHERE paused = false
    ORDER BY name
    """,
    ttl=0,
)
if orgs_df.empty:
    st.warning("No active organizations found.")
    st.stop()

org_label_to_id = {row["name"]: row["id"] for _, row in orgs_df.iterrows()}
selected_org_name = st.selectbox("Organization", options=list(org_label_to_id.keys()))
selected_org_id = org_label_to_id[selected_org_name]

# ========================== Step 2: Load campaigns for that org ==========================

org_campaign_rows = conn.query(
    """
    SELECT "campaignId"
    FROM smart_lead_campaigns
    WHERE "platformOrganizationId" = :org_id
    """,
    params={"org_id": selected_org_id},
    ttl=0,
)
org_campaign_ids = org_campaign_rows["campaignId"].astype(str).tolist()

with st.spinner("Fetching campaigns from Smartlead..."):
    all_smartlead_campaigns = get_smartlead_campaigns()
org_campaigns = [c for c in all_smartlead_campaigns if str(c.id) in org_campaign_ids]

if not org_campaigns:
    st.info(f"No Smartlead campaigns linked to **{selected_org_name}**.")
    st.stop()

campaign_label_to_id = {f"{c.name} (ID: {c.id})": str(c.id) for c in org_campaigns}
selected_campaign_label = st.selectbox(
    "Campaign", options=list(campaign_label_to_id.keys())
)
selected_campaign_id = campaign_label_to_id[selected_campaign_label]

# Clear stale results when campaign selection changes
if selected_campaign_id != ss["last_campaign_id"]:
    ss["job_results"] = None
    ss["last_select_all"] = False

# ========================== Step 3: Optional filters + Search ==========================

with st.form("query_form"):
    lead_email = st.text_input("Lead Email (optional)")
    submitted = st.form_submit_button("Search")

if submitted:
    conditions = ['"campaignId" = :campaign_id']
    params = {"campaign_id": selected_campaign_id}

    if lead_email:
        conditions.append('"leadEmail" = :lead_email')
        params["lead_email"] = lead_email.strip()

    where_clause = " AND ".join(conditions)

    query = f"""
    SELECT
      id,
      "createdAt",
      "updatedAt",
      "leadEmail",
      "campaignId",
      "platformOrganizationId",
      deadline,
      subject,
      "emailBody",
      status,
      error
    FROM auto_follow_up_jobs
    WHERE {where_clause}
    """

    try:
        results = conn.query(query, params=params, ttl=0)
    except Exception as e:
        st.error(f"Database query failed: {e}")
        st.stop()

    if results.empty:
        st.info("No auto follow-up jobs found for the given filters.")
        ss["job_results"] = None
        st.stop()

    results = results.sort_values(
        by="deadline", key=lambda col: col.astype(float)
    ).reset_index(drop=True)

    results["deadline_display"] = (
        pd.to_datetime(results["deadline"].astype(float), unit="ms", utc=True)
        .dt.tz_convert("America/New_York")
        .dt.strftime("%Y-%m-%d %H:%M:%S")
    )
    results.insert(0, "selected", False)
    ss["job_results"] = results
    ss["last_campaign_id"] = selected_campaign_id
    # Clear previous editor state so fresh data is shown
    if "job_table" in ss:
        del ss["job_table"]

if ss["job_results"] is None:
    st.stop()

st.success(f"Found {len(ss['job_results'])} job(s).")

# ========================== Display & Edit ==========================

select_all = st.checkbox("Select all rows")
if select_all != ss.get("last_select_all"):
    ss["last_select_all"] = select_all
    ss["job_results"] = ss["job_results"].copy()
    ss["job_results"]["selected"] = select_all
    st.rerun()

edited = st.data_editor(
    ss["job_results"],
    use_container_width=True,
    hide_index=True,
    disabled=[
        "id",
        "createdAt",
        "updatedAt",
        "platformOrganizationId",
        "deadline",
        "deadline_display",
    ],
    column_config={
        "selected": st.column_config.CheckboxColumn("Select", width="small"),
        "deadline": None,
        "deadline_display": st.column_config.TextColumn("Deadline (ET)"),
        "emailBody": st.column_config.TextColumn("emailBody", width="large"),
        "error": st.column_config.TextColumn("error", width="medium"),
    },
)

selected_ids = edited.loc[edited["selected"], "id"].tolist()

_, _, _, col3, col4 = st.columns([1, 1, 1, 1], gap="small")

with col3:
    if st.button("Mark as Completed", type="primary", disabled=not selected_ids):
        try:
            with conn.session as session:
                session.execute(
                    text(
                        "UPDATE auto_follow_up_jobs SET status = :status WHERE id = ANY(:ids)"
                    ),
                    {"status": "completed", "ids": selected_ids},
                )
                session.commit()
            st.success(f"Marked {len(selected_ids)} job(s) as completed.")
            ss["job_results"] = None
            st.rerun()
        except Exception as e:
            st.error(f"Failed to update status: {e}")

with col4:
    if st.button("Save Changes"):
        data_cols = [
            c for c in edited.columns if c not in ("selected", "deadline_display")
        ]
        changed_rows = edited[data_cols].compare(ss["job_results"][data_cols])

        if changed_rows.empty:
            st.info("No changes detected.")
            st.stop()

        changed_ids = changed_rows.index.tolist()
        updated_df = edited.loc[changed_ids]

        try:
            with conn.session as session:
                for _, row in updated_df.iterrows():
                    session.execute(
                        text(
                            """
                    UPDATE auto_follow_up_jobs
                    SET
                      "leadEmail"  = :lead_email,
                      "campaignId" = :campaign_id,
                      deadline     = :deadline,
                      subject      = :subject,
                      "emailBody"  = :email_body,
                      status       = :status,
                      error        = :error
                    WHERE id = :id
                    """
                        ),
                        {
                            "id": row["id"],
                            "lead_email": row["leadEmail"],
                            "campaign_id": row["campaignId"],
                            "deadline": row["deadline"],
                            "subject": row["subject"],
                            "email_body": row["emailBody"],
                            "status": row["status"],
                            "error": row["error"],
                        },
                    )
                session.commit()
            st.success(f"Updated {len(updated_df)} row(s) successfully.")
        except Exception as e:
            st.error(f"Failed to save changes: {e}")
