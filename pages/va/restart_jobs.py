import streamlit as st
import pandas as pd
from typing import List
from clients.cohesive.index import auto_schedule_restart_lead_generation_jobs

st.set_page_config(page_title="Running Lead Generation Jobs", layout="wide")

st.title("Running Lead Generation Jobs")

# Upload CSV
uploaded_file = st.file_uploader("Upload CSV containing a `name` column", type=["csv"])

if not uploaded_file:
    st.info("Upload a CSV file to get started.")
    st.stop()

# Read CSV
try:
    df = pd.read_csv(uploaded_file)
except Exception as e:
    st.error(f"Failed to read CSV: {e}")
    st.stop()

if "name" not in df.columns:
    st.error("CSV must contain a `name` column.")
    st.stop()

# Extract unique, non-null names
names: List[str] = df["name"].dropna().astype(str).str.strip().unique().tolist()

if not names:
    st.warning("No valid names found in CSV.")
    st.stop()

st.success(f"Loaded {len(names)} unique job names from CSV.")

# PostgreSQL connection
conn = st.connection("postgresql", type="sql")

# Build parameterized query safely
placeholders = ", ".join(["%s"] * len(names))

query = """
SELECT
  id,
  name,
  status,
  "createdAt",
  "updatedAt",
  "platformOrganizationId",
  type,
  "apolloRecordCount",
  "linearTicketUrl"
FROM lead_generation_jobs
WHERE status IN ('running', 'failed')
  AND name = ANY(:names)
ORDER BY "updatedAt" DESC
"""

# Execute query
try:
    results = conn.query(
        query, params={"names": names}, ttl=0  # disable caching for live job status
    )
except Exception as e:
    st.error(f"Database query failed: {e}")
    st.stop()

# Display results
if results.empty:
    st.warning("No running jobs found for uploaded names.")
else:
    st.subheader(f"Running Jobs ({len(results)})")
    st.dataframe(results, use_container_width=True, hide_index=True)

    # Restart jobs button
    if st.button("Restart Jobs", type="primary"):
        job_ids = results["id"].tolist()

        try:
            with st.spinner(f"Restarting {len(job_ids)} jobs..."):
                response = auto_schedule_restart_lead_generation_jobs(job_ids)

            # Parse response into DataFrame
            response_df = pd.DataFrame(response)

            # Convert startTimeMS to readable datetime
            if "startTimeMS" in response_df.columns:
                response_df["startTime"] = pd.to_datetime(
                    response_df["startTimeMS"], unit="ms", utc=True
                ).dt.strftime("%Y-%m-%d %H:%M:%S UTC")
                # Drop the original startTimeMS column
                response_df = response_df.drop(columns=["startTimeMS"])

            # Split into successful and failed
            successful_df = response_df[response_df["error"].isna()].copy()
            failed_df = response_df[response_df["error"].notna()].copy()

            # Display summary
            st.success(
                f"Restart complete: {len(successful_df)} succeeded, {len(failed_df)} failed"
            )

            # Successful refills table
            if not successful_df.empty:
                st.subheader(f"✅ Successful Refills ({len(successful_df)})")
                st.dataframe(successful_df, use_container_width=True, hide_index=True)

                # Download button for successful refills
                csv_success = successful_df.to_csv(index=False)
                st.download_button(
                    label="Download Successful Refills CSV",
                    data=csv_success,
                    file_name="successful_refills.csv",
                    mime="text/csv",
                    key="download_success",
                )

            # Failed refills table
            if not failed_df.empty:
                st.subheader(f"❌ Failed Refills ({len(failed_df)})")
                st.dataframe(failed_df, use_container_width=True, hide_index=True)

                # Download button for failed refills
                csv_failed = failed_df.to_csv(index=False)
                st.download_button(
                    label="Download Failed Refills CSV",
                    data=csv_failed,
                    file_name="failed_refills.csv",
                    mime="text/csv",
                    key="download_failed",
                )

        except Exception as e:
            st.error(f"Failed to restart jobs: {e}")
