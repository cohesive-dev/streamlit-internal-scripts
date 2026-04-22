import os

import streamlit as st
from azure.storage.blob import BlobServiceClient


def get_or_create_blob_service_client() -> BlobServiceClient:
    # Check env var first (deployed), then st.secrets (local dev)
    connection_str = os.environ.get("AZURE_STORAGE_CONNECTION_STRING") or str(
        st.secrets.get("AZURE_STORAGE_CONNECTION_STRING", "")
    )
    if not connection_str:
        raise RuntimeError("Missing AZURE_STORAGE_CONNECTION_STRING")
    return BlobServiceClient.from_connection_string(connection_str)
