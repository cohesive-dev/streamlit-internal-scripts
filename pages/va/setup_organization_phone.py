import streamlit as st
from twilio.rest import Client
from sqlalchemy import text


def get_secret(name: str) -> str:
    value = st.secrets.get(name)
    if value is None or str(value).strip() == "":
        raise RuntimeError(f"Missing required secret: {name}")
    return str(value)


def get_twilio_client() -> Client:
    return Client(
        get_secret("TWILIO_ACCOUNT_SID"),
        get_secret("TWILIO_AUTH_TOKEN"),
    )


def fetch_organizations(conn):
    # Returns a pandas DataFrame with columns: id, name, phone_number
    return conn.query(
        """
        SELECT "id", "name", "phoneNumber"
        FROM platform_organizations
        ORDER BY name ASC
        """,
        ttl=0,
    )


def update_org_phone_number(conn, org_id: str, phone_number: str):
    query = text(
        """
        UPDATE platform_organizations
        SET "phoneNumber" = :phone_number
        WHERE id = :org_id
        """
    )
    with conn.session as s:
        s.execute(
            query,
            {"phone_number": phone_number, "org_id": org_id},
        )
        s.commit()


st.title("Set Up Organization Twilio")

try:
    conn = st.connection("postgresql", type="sql")
    client = get_twilio_client()
    twilio_app_sid = get_secret("TWILIO_APP_SID")
except Exception as e:
    st.error(f"Initialization failed: {e}")

# 1) Fetch orgs from Postgres
try:
    org_df = fetch_organizations(conn)
except Exception as e:
    st.error(f"Failed to fetch organizations: {e}")

if org_df.empty:
    st.warning("No organizations found.")

org_df = org_df.fillna("")
org_options = {
    f"{row['name']} ({row['id']})": row["id"] for _, row in org_df.iterrows()
}

selected_org_label = st.selectbox(
    "Select an organization that you want to set up Twilio for",
    options=list(org_options.keys()),
)
selected_org_id = org_options[selected_org_label]

# 2) Endpoint input
url = st.text_input(
    "Enter your test endpoint (use ngrok for local testing)",
    placeholder="https://extension.cohesiveapp.com",
).strip()

# 3) Update Twilio app webhook + load numbers
if st.button("Load phone numbers", use_container_width=True):
    if not (url.startswith("http://") or url.startswith("https://")):
        st.error("Please enter a valid URL starting with http:// or https://")
        st.stop()

    try:
        with st.spinner("Updating Twilio application voice URL..."):
            client.applications(twilio_app_sid).update(
                voice_url=f"{url}/api/dialer/parallel",
                voice_method="GET",
            )

        with st.spinner("Fetching Twilio phone numbers..."):
            numbers = client.incoming_phone_numbers.list()

        if not numbers:
            st.warning("No incoming phone numbers found in this Twilio account.")
            st.stop()

        st.session_state["twilio_numbers"] = [
            {"sid": n.sid, "phone_number": n.phone_number} for n in numbers
        ]
        st.session_state["selected_org_id"] = selected_org_id
        st.session_state["selected_org_label"] = selected_org_label
        st.session_state["endpoint_url"] = url

        st.success("Application updated. Now select a phone number below.")
    except Exception as e:
        st.error(f"Failed to load phone numbers: {e}")
        st.stop()

# 4) Assign number to organization
twilio_numbers = st.session_state.get("twilio_numbers", [])
if twilio_numbers:
    number_map = {n["phone_number"]: n["sid"] for n in twilio_numbers}

    selected_phone_number = st.selectbox(
        "Select a phone number to assign to the organization",
        options=list(number_map.keys()),
        key="selected_phone_number",
    )
    selected_phone_sid = number_map[selected_phone_number]

    if st.button(
        "Assign number to organization", type="primary", use_container_width=True
    ):
        try:
            endpoint_url = st.session_state["endpoint_url"]
            org_id = st.session_state["selected_org_id"]

            with st.spinner("Updating selected Twilio phone number webhook..."):
                client.incoming_phone_numbers(selected_phone_sid).update(
                    voice_url=f"{endpoint_url}/api/dialer/incoming",
                    voice_method="POST",
                )

            with st.spinner("Updating organization record in PostgreSQL..."):
                update_org_phone_number(conn, org_id, selected_phone_number)

            st.success(
                f"✅ Assigned {selected_phone_number} to "
                f"{st.session_state['selected_org_label']} and updated webhooks."
            )
        except Exception as e:
            st.error(f"Failed to assign number: {e}")
