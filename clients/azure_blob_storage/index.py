import os
from azure.storage.blob import BlobServiceClient


def get_or_create_blob_service_client() -> BlobServiceClient:
    connection_str = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
    if not connection_str:
        raise RuntimeError("Missing AZURE_STORAGE_CONNECTION_STRING")
    return BlobServiceClient.from_connection_string(connection_str)
