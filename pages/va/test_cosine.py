import streamlit as st
import numpy as np
from openai import OpenAI

# Streamlit page config
st.title("Cosine Similarity of Two Terms (OpenAI Embeddings)")

# Get API key from Streamlit secrets
api_key = st.secrets["OPENAI_API_KEY"]
client = OpenAI(api_key=api_key)

# User inputs
term1 = st.text_input("Enter first term or sentence:", "")
term2 = st.text_input("Enter second term or sentence:", "")

model_name = "text-embedding-3-large"


def cosine_similarity(vec1, vec2):
    """Compute cosine similarity between two numpy vectors."""
    v1 = np.array(vec1)
    v2 = np.array(vec2)
    return np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2))


if st.button("Compute Similarity"):
    if not term1 or not term2:
        st.error("Please enter both terms before computing.")
        st.stop()

    with st.spinner("Generating embeddings..."):
        # Generate embeddings
        emb1 = client.embeddings.create(model=model_name, input=term1).data[0].embedding

        emb2 = client.embeddings.create(model=model_name, input=term2).data[0].embedding

        # Calculate cosine similarity
        similarity = cosine_similarity(emb1, emb2)

    st.subheader("Cosine Similarity Score")
    st.metric(label="Similarity", value=f"{similarity:.4f}")

    st.write(
        "**Tip:** Values closer to `1.0` mean more similar; closer to `0` mean unrelated."
    )
