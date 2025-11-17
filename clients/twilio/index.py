from twilio.rest import Client
import streamlit as st


def get_or_create_twilio_client():
    account_sid = st.secrets["TWILIO_ACCOUNT_SID"]
    auth_token = st.secrets["TWILIO_AUTH_TOKEN"]

    if not account_sid or not auth_token:
        raise ValueError("TWILIO_ACCOUNT_SID or TWILIO_AUTH_TOKEN is not set")

    return Client(account_sid, auth_token)
