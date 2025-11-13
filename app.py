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
            "pages/va/upload_dnc.py",
            title="Upload DNC List for Organization",
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
    ]
)
nav.run()
