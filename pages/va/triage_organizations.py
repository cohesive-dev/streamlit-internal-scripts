import streamlit as st
import pandas as pd


def get_all_organizations():
    """Get all organizations from the database."""
    conn = st.connection("postgresql", type="sql")
    query = """
    SELECT 
        id,
        name,
        paused,
        "createdAt",
        "updatedAt"
    FROM platform_organizations
    ORDER BY name ASC
    """
    orgs = conn.query(query, ttl=0)
    return list(orgs.to_dict(orient="records"))


def get_active_organizations():
    """Get only active (non-paused) organizations."""
    conn = st.connection("postgresql", type="sql")
    query = """
    SELECT 
        id,
        name,
        paused,
        "createdAt",
        "updatedAt"
    FROM platform_organizations
    WHERE paused = false
    ORDER BY name ASC
    """
    orgs = conn.query(query, ttl=0)
    return list(orgs.to_dict(orient="records"))


# Initialize session state
if "selected_org_ids" not in st.session_state:
    st.session_state.selected_org_ids = []

st.title("Triage Organizations")
st.markdown("Select and manage multiple organizations for triage operations.")

# Load only active organizations
with st.spinner("Loading organizations..."):
    organizations = get_active_organizations()

if not organizations:
    st.warning("No organizations found.")
    st.stop()

st.info(f"Found {len(organizations)} active organization(s)")

# Create organization options for multiselect
org_options = {f"{org['name']} (ID: {org['id']})": org for org in organizations}

# Multiselect for organizations
selected_org_labels = st.multiselect(
    "Select organizations",
    options=list(org_options.keys()),
    help="Search and select one or more organizations",
    placeholder="Type to search organizations...",
)

# Extract selected organization data
selected_orgs = [org_options[label] for label in selected_org_labels]
selected_org_ids = [org["id"] for org in selected_orgs]

# Store in session state
st.session_state.selected_org_ids = selected_org_ids

if selected_orgs:
    st.divider()
    st.subheader(f"Selected Organizations ({len(selected_orgs)})")

    # Display selected organizations in a table
    df = pd.DataFrame(selected_orgs)
    df = df[["id", "name", "paused", "createdAt", "updatedAt"]]
    df.columns = ["ID", "Name", "Paused", "Created At", "Updated At"]

    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
    )

    # Quick actions section
    st.divider()
    st.subheader("Quick Actions")

    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button("📋 Copy IDs", use_container_width=True):
            ids_text = "\n".join(selected_org_ids)
            st.code(ids_text)
            st.success("IDs displayed above - copy them manually")

    with col2:
        if st.button("📊 View Details", use_container_width=True):
            for org in selected_orgs:
                with st.expander(f"{org['name']}", expanded=False):
                    st.json(org)

    with col3:
        if st.button("🔄 Clear Selection", use_container_width=True):
            st.session_state.selected_org_ids = []
            st.rerun()

else:
    st.info("Select one or more organizations to get started.")
