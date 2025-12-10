import io

import pandas as pd
import streamlit as st
from azure.storage.blob import BlobServiceClient, ContentSettings
from sqlalchemy import text


def get_container_client():
    conn_str = st.secrets["AZURE_STORAGE_CONNECTION_STRING"]
    container = st.secrets["AZURE_DNC_STORAGE_CONTAINER"]
    if not conn_str:
        raise RuntimeError(
            "Missing AZURE_STORAGE_CONNECTION_STRING (env or st.secrets)."
        )
    if not container:
        raise RuntimeError("Missing AZURE_DNC_STORAGE_CONTAINER (env or st.secrets).")
    bsc = BlobServiceClient.from_connection_string(conn_str)
    return bsc.get_container_client(container)


def require_single_domain_column(df: pd.DataFrame) -> pd.Series:
    cols_lower = [c.strip().lower() for c in df.columns]
    if "domain" not in cols_lower:
        raise ValueError('CSV must contain a single column named "domain".')
    df = df.loc[:, [df.columns[cols_lower.index("domain")]]]
    if df.shape[1] != 1:
        raise ValueError('CSV must contain ONLY one column named "domain".')
    s = df.iloc[:, 0].astype(str).str.strip()
    if s.eq("").all():
        raise ValueError("No domains found in the CSV.")
    return s


conn = st.connection("postgresql", type="sql")
orgs = conn.query(
    'SELECT id, name, "dncListUrl" FROM platform_organizations ORDER BY name;', ttl=0
)
if orgs.empty:
    st.info("No organizations found.")
    st.stop()


label_to_id = {
    f"{row['name']} (ID: {row['id']})": row["id"] for _, row in orgs.iterrows()
}
choice = st.selectbox(
    "Choose the organization to upload a DNC list for:",
    options=list(label_to_id.keys()),
)
selected_id = label_to_id[choice]
selected_row = orgs.loc[orgs["id"] == selected_id].iloc[0]
if pd.notna(selected_row.dncListUrl) and str(selected_row.dncListUrl).strip():
    st.markdown(
        f"[🔗 Click to review current DNC list]({selected_row.dncListUrl})",
        help="Opens the currently stored DNC list for this organization.",
    )


file = st.file_uploader(
    'Select the CSV file containing the DNC list (must have a single column named "domain")',
    type=["csv"],
    accept_multiple_files=False,
)


if file and st.button("Upload DNC List"):
    try:
        content = file.read()
        df = pd.read_csv(io.BytesIO(content))
        domains = require_single_domain_column(df)
        clean_csv = domains.to_frame(name="domain").to_csv(index=False).encode("utf-8")
        container_client = get_container_client()
        blob_name = f"{selected_id}.csv"
        container_client.upload_blob(
            name=blob_name,
            data=clean_csv,
            overwrite=True,
            content_settings=ContentSettings(content_type="text/csv"),
        )
        blob_client = container_client.get_blob_client(blob_name)
        blob_url = blob_client.url
        with conn.session as s:
            s.execute(
                text(
                    'UPDATE platform_organizations SET "dncListUrl" = :url WHERE id = :id'
                ),
                {"url": blob_url, "id": selected_id},
            )
            s.commit()

        st.success("DNC list updated successfully.")
        st.markdown(f"[🔗 Click to view uploaded file]({blob_url})")

    except Exception as e:
        st.error(f"Upload failed: {e}")
