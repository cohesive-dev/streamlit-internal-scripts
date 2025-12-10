import streamlit as st
from sqlalchemy import text
from clients.twilio.index import get_or_create_twilio_client


def setup_organization_twilio():
    st.title("Set Up Organization Twilio")
    conn = st.connection("postgresql", type="sql")
    organizations = conn.query("SELECT * FROM platform_organizations", ttl=0).to_dict(
        orient="records"
    )
    org_options = {o["name"]: o["id"] for o in organizations}
    org_name = st.selectbox("Select an organization", list(org_options.keys()))
    selected_org_id = org_options[org_name]
    st.subheader("1. Select Twilio Phone Number")
    client = get_or_create_twilio_client()
    twilio_app_sid = st.secrets["TWILIO_APP_SID"]
    try:
        phone_numbers = client.incoming_phone_numbers.list()
    except Exception as e:
        st.error(f"Failed to fetch Twilio phone numbers: {e}")
        return
    number_map = {p.phone_number: p.sid for p in phone_numbers}
    selected_number_label = st.selectbox(
        "Choose a phone number", list(number_map.keys())
    )
    selected_number_sid = number_map[selected_number_label]

    st.subheader("2. Enter Test Endpoint")
    url = st.text_input("Enter your test endpoint (e.g. https://myapp.com)")
    if not url:
        st.stop()
    if st.button("Apply Twilio Setup"):
        try:
            client.applications(twilio_app_sid).update(
                voice_url=f"{url}/api/dialer/parallel", voice_method="GET"
            )
        except Exception as e:
            st.error(f"Error updating Twilio application: {e}")
            return

        try:
            client.incoming_phone_numbers(selected_number_sid).update(
                voice_url=f"{url}/api/dialer/incoming", voice_method="POST"
            )
        except Exception as e:
            st.error(f"Error updating phone number webhook: {e}")
            return

        try:
            with conn.session as session:
                session.execute(
                    text(
                        """
                        UPDATE platform_organizations
                        SET "phoneNumber" = :phone_number
                        WHERE id = :org_id;
                    """
                    ),
                    params={
                        "phone_number": selected_number_label,
                        "org_id": selected_org_id,
                    },
                )
                session.commit()
        except Exception as e:
            st.error(f"Error updating organization record: {e}")
            return

        st.success(f"Successfully assigned {selected_number_label} to {org_name}!")


setup_organization_twilio()
