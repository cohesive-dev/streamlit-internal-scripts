from openai import OpenAI
import csv
import io
import streamlit as st
import pandas as pd

from clients.azure_blob_storage.index import get_or_create_blob_service_client


def get_gpt_answer(system_prompt, user_prompt, temperature=0.7):
    openAIClient = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
    response = openAIClient.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
    )
    return response.choices[0].message.content.strip().lower()


def csv_to_json(file_content):
    return list(csv.DictReader(io.StringIO(file_content.decode("utf-8"))))


def json_to_csv(data, delimiter=","):
    if not data:
        return ""

    output = io.StringIO()
    fieldnames = data[0].keys()
    writer = csv.DictWriter(output, fieldnames=fieldnames, delimiter=delimiter)
    writer.writeheader()
    writer.writerows(data)
    return output.getvalue()


def chunk_list(lst, chunk_size):
    for i in range(0, len(lst), chunk_size):
        yield lst[i : i + chunk_size]


def upload_triage_data(data: list[dict], file_name: str) -> str:
    df = pd.DataFrame(data)
    tsv_buffer = io.BytesIO()
    df.to_csv(tsv_buffer, sep="\t", index=False)
    tsv_buffer.seek(0)

    blob_service_client = get_or_create_blob_service_client()
    container_name = st.secrets["SMARTLEAD_TRIAGE_CONTAINER"]
    if not container_name:
        raise RuntimeError("Missing SMARTLEAD_TRIAGE_CONTAINER environment variable.")
    container_client = blob_service_client.get_container_client(container_name)
    blob_client = container_client.get_blob_client(file_name)

    blob_client.upload_blob(
        tsv_buffer,
        overwrite=True,
        content_settings={"content_type": "text/tab-separated-values"},
    )

    blob_url = blob_client.url
    return blob_url
