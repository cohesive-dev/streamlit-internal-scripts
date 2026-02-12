import streamlit as st

nav = st.navigation(
    [
        st.Page("home.py", title="Home", icon="🏠"),
        st.Page(
            "pages/va/filter_leads_from_campaign.py", title="Filter Leads From Campaign"
        ),
        st.Page("pages/va/add_follow_ups.py", title="Add Follow-ups to Campaigns"),
        st.Page(
            "pages/va/apply_template_to_campaign.py",
            title="Apply Template to Campaign",
        ),
        st.Page(
            "pages/va/test_email.py",
            title="Send Test Email",
        ),
        st.Page(
            "pages/va/test_cosine.py",
            title="Test Cosine Similarity",
        ),
        st.Page(
            "pages/va/enable_auto_forward.py",
            title="Enable/Disable Auto Forward",
        ),
        st.Page(
            "pages/va/deduplicate_linear_tickets.py",
            title="Deduplicate Linear Tickets",
        ),
        st.Page(
            "pages/va/assign_linear_tickets.py",
            title="Assign Linear Tickets",
        ),
        st.Page(
            "pages/va/get_low_lead_orgs.py",
            title="Get Low Lead Organizations",
        ),
        st.Page(
            "pages/va/setup_organization_twilio.py",
            title="Set Up Organization Twilio",
        ),
        st.Page(
            "pages/va/remove_cohesive_accounts.py",
            title="Remove Cohesive Accounts",
        ),
        st.Page(
            "pages/va/ingest_cohesive_accounts.py",
            title="Ingest Cohesive Accounts",
        ),
        st.Page(
            "pages/va/set_whitelabel_config.py",
            title="Set Whitelabel Configuration",
        ),
        st.Page(
            "pages/va/link_campaigns.py",
            title="Link Campaigns to Organization",
        ),
        st.Page(
            "pages/va/restart_jobs.py",
            title="Restart Jobs",
        ),
        st.Page(
            "pages/va/mark_organizations_as_churned.py",
            title="Mark organizations as churned",
        ),
        st.Page(
            "pages/va/edit_campaign.py",
            title="Edit Campaign Template",
        ),
        st.Page(
            "pages/va/revert_campaign_template.py",
            title="Revert Campaign Template",
        ),
        st.Page(
            "pages/va/setup_organization_phone.py",
            title="Set Up Organization Phone",
        ),
    ]
)
nav.run()
