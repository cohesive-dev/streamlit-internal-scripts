import streamlit as st


def remove_cohesive_accounts():
    st.title("Remove Cohesive Accounts")
    conn = st.connection("postgresql", type="sql")
    organizations = conn.query(
        "SELECT id, name FROM platform_organizations ORDER BY name;", ttl=0
    )
    if len(organizations) == 0:
        st.write("No organizations found.")
        return
    org_name_to_id = {row["name"]: row["id"] for _, row in organizations.iterrows()}
    selected_org_name = st.selectbox(
        "Select the organization to remove accounts for:", list(org_name_to_id.keys())
    )
    selected_org_id = org_name_to_id[selected_org_name]
    if st.button(f"Remove ALL accounts for '{selected_org_name}'"):
        st.warning(
            f"Are you sure you want to permanently delete ALL accounts for "
            f"**{selected_org_name}**?"
        )
        if st.button("Yes, delete all accounts now"):
            with conn.session as session:
                session.execute(
                    f"""
                        DELETE FROM accounts
                        WHERE "platformOrganizationId" = {selected_org_id}
                        """
                )
                session.commit()
            st.success(f"All accounts for **{selected_org_name}** have been removed.")


remove_cohesive_accounts()
