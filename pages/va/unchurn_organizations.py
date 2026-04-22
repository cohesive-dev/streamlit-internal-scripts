import json

import streamlit as st
from sqlalchemy import text

from azure.storage.blob import ContentSettings
from clients.azure_blob_storage.index import get_or_create_blob_service_client

SCHEDULED_PAUSES_BLOB = "scheduled-campaign-pauses.json"


def get_churned_organizations():
    """Fetch all orgs currently marked as churned (paused=true) for the unchurn UI."""
    conn = st.connection("postgresql", type="sql")
    with conn.session as session:
        result = session.execute(
            text(
                """
                SELECT id, name
                FROM platform_organizations
                WHERE paused = true
                ORDER BY name ASC
                """
            )
        )
        orgs = [{"id": row[0], "name": row[1]} for row in result]
    return orgs


def unpause_platform_organizations(org_ids: list[str]) -> int:
    """Reverse a churn: set paused=false for the given orgs. Returns rows updated."""
    if not org_ids:
        return 0

    query = text(
        """
      UPDATE platform_organizations
      SET "paused" = false,
          "updatedAt" = NOW()
      WHERE id = ANY(:org_ids)
    """
    )

    conn = st.connection("postgresql", type="sql")
    with conn.session as session:
        result = session.execute(query, {"org_ids": org_ids})
        updated_count = result.rowcount
        session.commit()

    return updated_count


# --- Blob helpers for scheduled pauses ---


def _get_blob_client():
    blob_service = get_or_create_blob_service_client()
    container = blob_service.get_container_client(
        st.secrets["SMARTLEAD_TRIAGE_CONTAINER"]
    )
    return container.get_blob_client(SCHEDULED_PAUSES_BLOB)


def load_scheduled_pauses() -> list[dict]:
    """Load scheduled pauses from blob. Returns [] if blob doesn't exist."""
    blob_client = _get_blob_client()
    data = blob_client.download_blob().readall()
    return json.loads(data)


def save_scheduled_pauses(entries: list[dict]) -> None:
    """Write scheduled pauses to blob (overwrites)."""
    blob_client = _get_blob_client()
    blob_client.upload_blob(
        json.dumps(entries, indent=2).encode("utf-8"),
        overwrite=True,
        content_settings=ContentSettings(
            content_type="application/json", cache_control="no-cache"
        ),
    )


def remove_scheduled_pauses_for_orgs(org_ids: list[str]) -> int:
    """Cancel scheduled pauses for the given orgs by removing them from blob storage.
    Used when a customer is saved/unchurned, or when a scheduled pause is manually cancelled.
    """
    existing = load_scheduled_pauses()
    org_id_set = set(org_ids)
    kept = [e for e in existing if e["org_id"] not in org_id_set]
    removed = len(existing) - len(kept)
    if removed > 0:
        save_scheduled_pauses(kept)
    return removed


st.title("Unchurn Organizations")

# --- Pending scheduled pauses + cancel ---
# Shows all future-dated pauses from blob storage with the ability to cancel them.
# Useful when a customer is saved mid-churn, or when the org was already manually
# unpaused in Supabase but the scheduled pause entry is still hanging around.
st.subheader("Pending Scheduled Pauses")
try:
    pending = load_scheduled_pauses()
    if pending:
        # Group by org for the cancel selector
        pending_orgs = {}
        for e in pending:
            key = f"{e['org_name']} (ID: {e['org_id']}, pause: {e['pause_date']})"
            pending_orgs.setdefault(key, []).append(e)

        st.dataframe(
            [
                {
                    "Org": e["org_name"],
                    "Campaign ID": e["campaign_id"],
                    "Pause Date": e["pause_date"],
                    "Scheduled On": e["created_at"],
                }
                for e in pending
            ],
            use_container_width=True,
        )

        # Cancel UI — select by org
        cancel_selected = st.multiselect(
            "Select scheduled pauses to cancel",
            options=list(pending_orgs.keys()),
            help="Select one or more orgs to remove their scheduled campaign pauses",
            key="cancel_scheduled_select",
        )

        if cancel_selected and st.button("Cancel selected scheduled pauses"):
            org_ids_to_cancel = set()
            for key in cancel_selected:
                for e in pending_orgs[key]:
                    org_ids_to_cancel.add(e["org_id"])
            removed = remove_scheduled_pauses_for_orgs(list(org_ids_to_cancel))
            st.success(f"Cancelled {removed} scheduled campaign pause(s)")
            st.rerun()
    else:
        st.caption("No scheduled pauses pending.")
except Exception as e:
    st.error(f"Could not load scheduled pauses: {e}")

# --- Unchurn (reactivate org in DB) ---
# Separate from the cancel-scheduled-pause flow above. This handles the case where
# the org is still marked paused=true in the DB and needs to be flipped back.
st.divider()
st.subheader("Unchurn Organization")
st.caption(
    "Reactivate a churned org in the database (sets paused = false). "
    "Use this when the org is still marked as churned in Supabase."
)

churned_orgs = get_churned_organizations()

if churned_orgs:
    churned_org_names = [f"{org['name']} (ID: {org['id']})" for org in churned_orgs]
    unchurn_selected = st.multiselect(
        "Select organizations to reactivate",
        options=churned_org_names,
        help="Search and select one or more churned organizations",
        key="unchurn_select",
    )

    unchurn_org_ids = []
    if unchurn_selected:
        for selected in unchurn_selected:
            org_id = selected.split("ID: ")[1].rstrip(")")
            unchurn_org_ids.append(org_id)

    if unchurn_selected and st.button("Reactivate organizations"):
        updated = unpause_platform_organizations(unchurn_org_ids)
        st.success(f"Reactivated {updated} organization(s)")

        # Also clean up any leftover scheduled pauses for these orgs
        removed = remove_scheduled_pauses_for_orgs(unchurn_org_ids)
        if removed > 0:
            st.success(f"Also cancelled {removed} scheduled campaign pause(s)")
        st.rerun()
else:
    st.caption("No churned organizations found.")
