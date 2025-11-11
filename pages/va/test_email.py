from azure.communication.email import EmailClient
import streamlit as st
import resend


def send_email(to_address):
    try:
        resend.api_key = st.secrets["RESEND_API_KEY"]
        params: resend.Emails.SendParams = {
            "from": "DoNotReply@test.getcohesiveai.com",
            "to": [to_address],
            "subject": "hello world",
            "html": "<strong>it works!</strong>",
        }
        email = resend.Emails.send(params)
    except Exception as ex:
        st.error(f"Error sending email: {ex}")
        return None


# Streamlit UI
st.title("Send Test Email")

to_address = st.text_input(
    "Enter recipient email address:", value="nam@cohesiveapp.com"
)

if st.button("Send Email"):
    if to_address:
        with st.spinner("Sending email..."):
            message_id = send_email(to_address)
            if message_id:
                st.success(f"Email sent successfully! Message ID: {message_id}")
            else:
                st.error("Failed to send email.")
    else:
        st.warning("Please enter a valid email address.")
