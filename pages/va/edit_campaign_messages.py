import streamlit as st
from datetime import datetime
from typing import List, Dict

from clients.smartlead.index import (
    SmartleadCampaignSequenceInput,
    add_sequences_to_campaign,
    get_campaign_sequences,
    get_campaigns,
)


def replace_phrases_inside_template(
    smartlead_campaign_id: int,
    phrases_to_replace: List[str],
    replacement_text: str,
):
    sequences = get_campaign_sequences(smartlead_campaign_id)
    updated_sequences = []
    for sequence in sequences:
        if sequence.sequence_variants:
            updated_variants = []
            for variant in sequence.sequence_variants:
                updated_email_body = variant.email_body

                for phrase in phrases_to_replace:
                    updated_email_body = updated_email_body.replace(
                        phrase, replacement_text
                    )

                updated_variants.append(
                    variant.model_copy(update={"email_body": updated_email_body})
                )

            updated_sequences.append(
                sequence.model_copy(update={"sequence_variants": updated_variants})
            )
        else:
            updated_email_body = sequence.email_body

            for phrase in phrases_to_replace:
                updated_email_body = updated_email_body.replace(
                    phrase, replacement_text
                )

            updated_sequences.append(
                sequence.model_copy(update={"email_body": updated_email_body})
            )
    input_sequences = []
    for seq in updated_sequences:
        input_sequences.append(
            SmartleadCampaignSequenceInput(
                seq_number=sequence.seq_number,
                email_body=updated_email_body,
                subject=sequence.subject,
                seq_delay_details={
                    "delay_in_days": sequence.seq_delay_details.delayInDays
                },
                seq_variants=(
                    [
                        {
                            "subject": v.subject,
                            "email_body": v.email_body,
                            "variant_label": v.variant_label,
                            "variant_distribution_percentage": v.variant_distribution_percentage,
                        }
                        for v in updated_variants
                    ]
                    if updated_variants
                    else None
                ),
            )
        )

    add_sequences_to_campaign(
        campaign_id=smartlead_campaign_id,
        input_sequences=input_sequences,
    )


def edit_campaign_messages():
    st.header("✏️ Rewrite Smartlead Campaign Templates")
    conn = st.connection("postgresql", type="sql")
    with st.spinner("Fetching Smartlead campaigns..."):
        campaigns = get_campaigns()
    campaigns_by_id = {str(c.id): c for c in campaigns}
    campaigns_to_rewrite: List[Dict] = []
    campaign_options = [f"{c.name} (ID: {c.id})" for c in campaigns]
    selected_labels = st.multiselect(
        "Select campaign(s) to rewrite",
        options=campaign_options,
    )
    for label in selected_labels:
        campaign_id = label.split("ID: ")[-1].replace(")", "")
        campaign = campaigns_by_id.get(campaign_id)
        if campaign:
            campaigns_to_rewrite.append({"id": campaign.id, "name": campaign.name})
    phrases_raw = st.text_input(
        "Phrases to replace (semicolon separated)",
        placeholder="Hello there;Hope you're well",
    )
    replacement_text = st.text_input(
        "Replacement text",
        placeholder="Hi {{first_name}}",
    )
    phrases_to_replace = [p.strip() for p in phrases_raw.split(";") if p.strip()]
    if st.button(f"🚀 Rewrite {len(campaigns_to_rewrite)} campaign(s)"):
        if not campaigns_to_rewrite:
            st.warning("No campaigns selected.")
            return
        if not phrases_to_replace or not replacement_text:
            st.warning("Please provide phrases and replacement text.")
            return
        successful = []
        failed = []
        progress = st.progress(0)
        total = len(campaigns_to_rewrite)
        for idx, campaign in enumerate(campaigns_to_rewrite, start=1):
            try:
                replace_phrases_inside_template(
                    smartlead_campaign_id=campaign.get("id"),
                    phrases_to_replace=phrases_to_replace,
                    replacement_text=replacement_text,
                )
                successful.append(campaign)
            except Exception as e:
                st.error(f"Error rewriting campaign {campaign['id']}: {e}")
                failed.append(campaign)

            progress.progress(idx / total)
        if successful:
            st.subheader("✅ Successfully Rewritten Campaigns")
            rows = []
            for c in successful:
                rows.append(
                    f"| {c.get("name")} | "
                    f"[View Campaign](https://app.smartlead.ai/app/email-campaign/{c.get("id")}/analytics) |"
                )

            markdown_table = "\n".join(
                [
                    "| Campaign Name | Link |",
                    "|---------------|------|",
                    *rows,
                ]
            )
            st.markdown(markdown_table)
        if failed:
            st.subheader("❌ Failed Campaigns")
            for c in failed:
                st.write(f"- {c['name']} (ID: {c['id']})")


edit_campaign_messages()
