import streamlit as st
from typing import Any, Dict, List, Optional, TypedDict
from clients.smartlead.index import (
    get_campaigns,
    get_campaign_sequences,
    add_sequences_to_campaign,
)
from clients.smartlead.schema import SmartleadCampaignSequenceInput
import re


def templatize_email_body(
    email_body: Optional[str], company_name: str, title: Optional[str] = None
) -> Optional[str]:
    if email_body is None:
        return None

    # Regex pattern to match "name" not preceded by %sender-, first_, or last_
    # and not followed by %
    regex = r"(?<!%sender-)(?<!first_)(?<!last_)(?:\()?name(?:\))?(?!%)"

    final_email_body = re.sub(regex, "%sender-name%", email_body, flags=re.IGNORECASE)

    if company_name:
        final_email_body = final_email_body.replace("Company", company_name)

    if title:
        final_email_body = final_email_body.replace("Title", title)

    return final_email_body


def apply_template_to_campaign_helper(
    *,
    smartlead_campaign_id: int,
    smartlead_template_id: int,
    company_name: str,
) -> None:
    template_sequences: List[Dict[str, Any]] = get_campaign_sequences(
        smartlead_template_id
    )
    current_sequences: List[Dict[str, Any]] = get_campaign_sequences(
        smartlead_campaign_id
    )

    input_sequences: List[SmartleadCampaignSequenceInput] = []
    for index, seq in enumerate(template_sequences):
        existing_id = None
        if index < len(current_sequences):
            existing_id = current_sequences[index].id

        raw_variants = seq.sequence_variants or None
        sequence_variants: Optional[List] = None

        if raw_variants:
            sequence_variants = [
                {
                    "subject": v.subject,
                    "email_body": templatize_email_body(v.email_body, company_name),
                    "variant_label": v.variant_label,
                    "variant_distribution_percentage": v.variant_distribution_percentage,
                }
                for v in raw_variants
            ]

        input_sequences.append(
            SmartleadCampaignSequenceInput(
                id=existing_id,
                seq_number=int(seq.seq_number or index + 1),
                subject=seq.subject,
                email_body=templatize_email_body(seq.email_body, company_name),
                seq_delay_details={
                    "delay_in_days": int(seq.seq_delay_details.delayInDays)
                },
                seq_variants=sequence_variants,
            )
        )

    add_sequences_to_campaign(
        campaign_id=smartlead_campaign_id,
        input_sequences=input_sequences,
    )


# ---------- UI ----------
st.title("Apply Template to Campaign")

# Session flags
ss = st.session_state
ss.setdefault("all_campaigns", [])
ss.setdefault("running_apply_template", False)

# Load campaigns once
with st.spinner("Loading campaigns..."):
    ss.all_campaigns = get_campaigns()

if not ss.all_campaigns:
    st.error("No campaigns found.")
    st.stop()


# Build option labels
def _label(c: Dict[str, Any]) -> str:
    return f"Campaign ID: {c.id}, name: {c.name}"


campaign_options = {_label(c): c for c in ss.all_campaigns}

template_label = st.selectbox(
    "Select the template to use",
    options=list(campaign_options.keys()),
    index=0,
    key="template_to_use_label",
)
target_label = st.selectbox(
    "Select the campaign to rewrite",
    options=list(campaign_options.keys()),
    index=min(1, len(campaign_options) - 1),
    key="campaign_to_rewrite_label",
)

company_name = st.text_input("Enter the company name", key="company_name")

# Guardrails
template_campaign = campaign_options[template_label]
target_campaign = campaign_options[target_label]

if template_campaign.id == target_campaign.id:
    st.warning("Template and target campaign must be different.")

disabled = (
    not company_name.strip()
    or template_campaign.id == target_campaign.id
    or ss["running_apply_template"]
)

if st.button("Apply Template", type="primary", disabled=disabled):
    ss["running_apply_template"] = True
    try:
        with st.spinner("Applying template..."):
            apply_template_to_campaign_helper(
                smartlead_campaign_id=int(target_campaign.id),
                smartlead_template_id=int(template_campaign.id),
                company_name=company_name.strip(),
            )
        st.success(
            f"✅ Template from Campaign {template_campaign.id} applied to Campaign {target_campaign.id} for “{company_name.strip()}”."
        )
    except Exception as e:
        st.error(f"Failed to apply template: {e}")
    finally:
        ss["running_apply_template"] = False
