from azure.communication.email import EmailClient
import streamlit as st
import resend
import pandas as pd


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
        return email
    except Exception as ex:
        st.error(f"Error sending email to {to_address}: {ex}")
        return None


def send_bulk_emails(email_list):
    success_count = 0
    failed_emails = []

    progress_bar = st.progress(0)
    for i, email in enumerate(email_list):
        result = send_email(email.strip())
        if result:
            success_count += 1
        else:
            failed_emails.append(email)
        progress_bar.progress((i + 1) / len(email_list))

    return success_count, failed_emails


# Streamlit UI
st.title("Send Test Email")

# Option to send single email
st.subheader("Send Single Email")
to_address = st.text_input(
    "Enter recipient email address:", value="nam@cohesiveapp.com"
)

if st.button("Send Single Email"):
    if to_address:
        with st.spinner("Sending email..."):
            result = send_email(to_address)
            if result:
                st.success(f"Email sent successfully!")
            else:
                st.error("Failed to send email.")
    else:
        st.warning("Please enter a valid email address.")

# Option to upload CSV/TSV file
st.subheader("Send Bulk Emails")
uploaded_file = st.file_uploader("Choose a CSV or TSV file", type=["csv", "tsv"])

if uploaded_file is not None:
    try:
        # Determine separator based on file extension
        separator = "\t" if uploaded_file.name.endswith(".tsv") else ","

        # Read the file
        df = pd.read_csv(uploaded_file, sep=separator)

        # Show available columns
        email_column = st.selectbox("Select the email column:", df.columns)

        # Preview the data
        st.write(f"Preview of {len(df)} rows:")
        st.dataframe(df.head())

        if st.button("Send Bulk Emails"):
            email_list = df[email_column].dropna().tolist()

            if email_list:
                with st.spinner(f"Sending {len(email_list)} emails..."):
                    success_count, failed_emails = send_bulk_emails(email_list)

                st.success(
                    f"Successfully sent {success_count} out of {len(email_list)} emails"
                )

                if failed_emails:
                    st.error(f"Failed to send emails to: {', '.join(failed_emails)}")
            else:
                st.warning("No valid email addresses found in the selected column.")

    except Exception as e:
        st.error(f"Error reading file: {e}")
