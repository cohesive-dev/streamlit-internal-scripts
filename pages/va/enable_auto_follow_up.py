import streamlit as st
from sqlalchemy import text

st.title("Enable / Disable Auto Follow-Up With Interested Lead")

conn = st.connection("postgresql", type="sql")

orgs_df = conn.query(
    """
    SELECT id, name, "autoFollowUpWithInterestedLead"
    FROM platform_organizations
    WHERE paused = false
    ORDER BY name
    """,
    ttl=0,
)

if orgs_df.empty:
    st.warning("No active organizations found.")
    st.stop()

enabled_ids = set(orgs_df.loc[orgs_df["autoFollowUpWithInterestedLead"], "id"].tolist())

org_label_to_id = {
    f"{row['name']} ({'ON' if row['id'] in enabled_ids else 'OFF'})": row["id"]
    for _, row in orgs_df.iterrows()
}

selected_labels = st.multiselect(
    "Select organizations",
    options=list(org_label_to_id.keys()),
)

if not selected_labels:
    st.stop()

selected_ids = [org_label_to_id[label] for label in selected_labels]

col1, col2 = st.columns(2)

with col1:
    if st.button("Enable", type="primary", use_container_width=True):
        with conn.session as s:
            s.execute(
                text(
                    'UPDATE platform_organizations SET "autoFollowUpWithInterestedLead" = true WHERE id = ANY(:ids)'
                ),
                {"ids": selected_ids},
            )
            s.commit()
        st.success(f"Enabled auto follow-up for {len(selected_ids)} org(s).")
        st.rerun()

with col2:
    if st.button("Disable", use_container_width=True):
        with conn.session as s:
            s.execute(
                text(
                    'UPDATE platform_organizations SET "autoFollowUpWithInterestedLead" = false WHERE id = ANY(:ids)'
                ),
                {"ids": selected_ids},
            )
            s.commit()
        st.success(f"Disabled auto follow-up for {len(selected_ids)} org(s).")
        st.rerun()
