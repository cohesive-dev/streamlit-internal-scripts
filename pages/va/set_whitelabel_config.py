import streamlit as st
from sqlalchemy import text


def set_whitelabel_config():
    st.header("Set Whitelabel Configuration")

    whitelabelName = st.text_input("Enter name of the whitelabel partner")
    whitelabelDomain = st.text_input("Enter domain of the whitelabel partner")
    whitelabelNotificationEmail = st.text_input(
        "Enter notification email for the whitelabel partner"
    )
    whitelabelNotificationBCCEmails = st.text_input(
        "Enter BCC emails (comma separated) for the whitelabel partner"
    )
    whitelabelSupportEmail = st.text_input(
        "Enter support email for the whitelabel partner"
    )
    whitelabelNotificationPhone = st.text_input(
        "Enter notification phone for the whitelabel partner"
    )
    appDomain = st.text_input("Enter app domain for the whitelabel partner")

    conn = st.connection("postgresql", type="sql")

    if st.button("Save Configuration"):
        if not all(
            [
                whitelabelName,
                whitelabelDomain,
                whitelabelNotificationEmail,
                whitelabelSupportEmail,
                whitelabelNotificationPhone,
                appDomain,
            ]
        ):
            st.error("Please fill in all required fields.")
            return

        appUrl = f"https://{appDomain}/inbox"

        with st.spinner("Saving label configuration…"):
            with conn.session as session:
                session.execute(
                    text(
                        """
                        INSERT INTO "label_configs" (
                            "id",
                            "createdAt",
                            "updatedAt",
                            "whitelabelName",
                            "whitelabelDomain",
                            "whitelabelNotificationEmail",
                            "whitelabelNotificationBCCEmails",
                            "whitelabelSupportEmail",
                            "whitelabelNotificationPhone",
                            "appUrl"
                        ) VALUES (
                            gen_random_uuid()::text,
                            NOW(),
                            NOW(),
                            :whitelabelName,
                            :whitelabelDomain,
                            :whitelabelNotificationEmail,
                            :whitelabelNotificationBCCEmails,
                            :whitelabelSupportEmail,
                            :whitelabelNotificationPhone,
                            :appUrl
                        )
                        ON CONFLICT ("whitelabelDomain")
                        DO UPDATE SET
                            "updatedAt" = NOW(),
                            "whitelabelName" = EXCLUDED."whitelabelName",
                            "whitelabelNotificationEmail" = EXCLUDED."whitelabelNotificationEmail",
                            "whitelabelNotificationBCCEmails" = EXCLUDED."whitelabelNotificationBCCEmails",
                            "whitelabelSupportEmail" = EXCLUDED."whitelabelSupportEmail",
                            "whitelabelNotificationPhone" = EXCLUDED."whitelabelNotificationPhone",
                            "appUrl" = EXCLUDED."appUrl";
                    """
                    ),
                    {
                        "whitelabelName": whitelabelName,
                        "whitelabelDomain": whitelabelDomain,
                        "whitelabelNotificationEmail": whitelabelNotificationEmail,
                        "whitelabelNotificationBCCEmails": whitelabelNotificationBCCEmails,
                        "whitelabelSupportEmail": whitelabelSupportEmail,
                        "whitelabelNotificationPhone": whitelabelNotificationPhone,
                        "appUrl": appUrl,
                    },
                )
                session.commit()

        st.success("Whitelabel configuration saved successfully!")


set_whitelabel_config()
