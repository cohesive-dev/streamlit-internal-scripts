import streamlit as st
import pandas as pd
from typing import List, Dict
from io import StringIO


def csv_to_json(csv_text: str, delimiter: str):
    df = pd.read_csv(StringIO(csv_text), delimiter=delimiter)
    return df.to_dict(orient="records")


def safe_parse_phone_e164(raw: str) -> str:
    """Very simplified E164 parser."""
    digits = "".join([c for c in raw if c.isdigit()])
    if digits.startswith("1"):
        return f"+{digits}"
    if len(digits) == 10:
        return f"+1{digits}"
    return ""


def compact(arr: List):
    return [x for x in arr if x is not None]


def ingest_cohesive_account_from_smartlead():
    st.header("Ingest Cohesive Accounts from Smartlead CSV")

    conn = st.connection("postgresql", type="sql")

    organizations = conn.query("SELECT id, name FROM platform_organizations", ttl=0)

    org_options = {row["name"]: row["id"] for _, row in organizations.iterrows()}

    selected_org_label = st.selectbox(
        "Select the organization to ingest the account for",
        options=list(org_options.keys()),
    )
    organization_id = org_options[selected_org_label]

    uploaded_file = st.file_uploader(
        "Select the CSV/TSV file containing accounts to ingest", type=["csv", "tsv"]
    )

    if not uploaded_file:
        return

    content = uploaded_file.read().decode("utf-8")
    delimiter = "\t" if uploaded_file.name.endswith(".tsv") else ","

    json_rows = csv_to_json(content, delimiter)

    accounts_to_ingest: List[Dict] = []

    for row in json_rows:
        company_name = row.get("Company Name", "").strip()
        if not company_name:
            continue

        phone = safe_parse_phone_e164(str(row.get("Phone Number", "") or ""))

        accounts_to_ingest.append(
            {
                "platform_organization_id": organization_id,
                "phone": phone,
                "name": company_name,
                "domain": row.get("Website", "") or "",
                "address": row.get("Location", "") or "",
                "description": row.get("informalIndustry", "") or "",
                "owner_first_name": row.get("First Name", "") or "",
                "owner_last_name": row.get("Last Name", "") or "",
                "email": row.get("Email", "") or "",
            }
        )

    accounts_to_ingest = compact(accounts_to_ingest)

    st.write(f"Found **{len(accounts_to_ingest)}** valid accounts.")

    if not st.button(f"Ingest {len(accounts_to_ingest)} accounts?"):
        return

    success_count = 0

    for account in accounts_to_ingest:
        conn.query(
            """
      INSERT INTO account (
        platform_organization_id, phone, name, domain,
        address, description, owner_first_name,
        owner_last_name, email
      ) VALUES (
        %(platform_organization_id)s, %(phone)s, %(name)s, %(domain)s,
        %(address)s, %(description)s, %(owner_first_name)s,
        %(owner_last_name)s, %(email)s
      )
      ON CONFLICT DO NOTHING;
      """,
            params=account,
            ttl=0,
        )
        success_count += 1

    st.success(f"Successfully ingested {success_count} accounts!")


ingest_cohesive_account_from_smartlead()
