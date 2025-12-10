import streamlit as st
from sqlalchemy import text


def get_active_organizations():
    conn = st.connection("postgresql", type="sql")
    query = """
SELECT *
  FROM platform_organizations
  where paused = false
"""
    campaigns = conn.query(query, ttl=0)
    return list(campaigns.to_dict(orient="records"))


def update_org_email_forwarding(org_id: int, enabled: bool, email: str | None):
    conn = st.connection("postgresql", type="sql")

    query = text(
        """
        UPDATE platform_organizations
        SET "emailAutoForward" = :enabled,
            "autoforwardEmail" = :email
        WHERE id = :org_id
    """
    )

    with conn.session as s:
        s.execute(query, {"enabled": enabled, "email": email, "org_id": org_id})
        s.commit()


st.title("Manage Auto Forward Settings")

selection = st.radio(
    "Do you want to enable or disable auto forward?",
    options=["enable", "disable"],
    format_func=lambda x: (
        "Enable Auto Forward" if x == "enable" else "Disable Auto Forward"
    ),
)

organizations = get_active_organizations()

if selection == "enable":
    org_options = {f"{org["name"]}": org["id"] for org in organizations}

    selected_orgs = st.multiselect(
        "Select organizations to enable auto forward for:",
        options=list(org_options.keys()),
    )

    if selected_orgs:
        st.write("Enter the forwarding email(s) for each selected organization:")

    for org_name in selected_orgs:
        org_id = org_options[org_name]
        email_input = st.text_input(
            f"Enter comma-separated emails for {org_name} (ID: {org_id})",
            key=f"email_{org_id}",
        )

        if st.button(f"Enable Auto Forward for {org_name}", key=f"enable_{org_id}"):
            update_org_email_forwarding(org_id=org_id, enabled=True, email=email_input)
            st.success(f"Auto forward enabled for {org_name}")

else:
    active_forwarding_orgs = [
        org for org in organizations if org.get("emailAutoForward")
    ]

    org_options = {f"{org["name"]}": org["id"] for org in organizations}

    selected_orgs = st.multiselect(
        "Select organizations to disable auto forward for:",
        options=list(org_options.keys()),
    )

    for org_name in selected_orgs:
        org_id = org_options[org_name]

        if st.button(f"Disable Auto Forward for {org_name}", key=f"disable_{org_id}"):
            update_org_email_forwarding(org_id=org_id, enabled=False, email=None)
            st.success(f"Auto forward disabled for {org_name}")
