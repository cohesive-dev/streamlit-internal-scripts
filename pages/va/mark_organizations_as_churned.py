import json
from datetime import date, timedelta

import streamlit as st
from sqlalchemy import text

from azure.storage.blob import ContentSettings
from clients.azure_blob_storage.index import get_or_create_blob_service_client

SCHEDULED_PAUSES_BLOB = "scheduled-campaign-pauses.json"


def get_active_organizations():
    conn = st.connection("postgresql", type="sql")
    with conn.session as session:
        result = session.execute(
            text(
                """
                SELECT id, name
                FROM platform_organizations
                WHERE paused = false
                ORDER BY name ASC
                """
            )
        )
        orgs = [{"id": row[0], "name": row[1]} for row in result]
    return orgs


def pause_platform_organizations(
    org_ids: list[str] | None = None,
) -> int:
    """
    Returns number of rows updated.
    """

    if not org_ids:
        return 0

    query = text(
        """
      UPDATE platform_organizations
      SET "paused" = true,
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


def get_campaign_ids_for_orgs(org_ids: list[str]) -> dict[str, list[int]]:
    """Get Smartlead campaign IDs tied to each org from the DB."""
    conn = st.connection("postgresql", type="sql")
    query = """
        SELECT "platformOrganizationId" as org_id, "campaignId" as campaign_id
        FROM smart_lead_campaigns
        WHERE "platformOrganizationId" = ANY(:org_ids)
    """
    df = conn.query(query, params={"org_ids": org_ids}, ttl=0)

    result: dict[str, list[int]] = {}
    for _, row in df.iterrows():
        org_id = row["org_id"]
        campaign_id = int(str(row["campaign_id"]).strip())
        result.setdefault(org_id, []).append(campaign_id)
    return result


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
    try:
        data = blob_client.download_blob().readall()
        return json.loads(data)
    except Exception:
        return []


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


def add_scheduled_pauses(
    org_ids: list[str],
    org_names: list[str],
    campaigns_by_org: dict[str, list[int]],
    pause_date: date,
) -> int:
    """Append scheduled pause entries to the blob. Returns count of campaigns scheduled."""
    existing = load_scheduled_pauses()
    count = 0
    for org_id, org_name in zip(org_ids, org_names):
        campaign_ids = campaigns_by_org.get(org_id, [])
        for cid in campaign_ids:
            existing.append(
                {
                    "org_id": org_id,
                    "org_name": org_name,
                    "campaign_id": cid,
                    "pause_date": pause_date.isoformat(),
                    "created_at": date.today().isoformat(),
                }
            )
            count += 1
    save_scheduled_pauses(existing)
    return count


def unlink_campaigns_from_org(campaign_ids: list[int]) -> dict[str, list]:
    """Set platformOrganizationId to null for the given campaigns so the org loses access."""
    conn = st.connection("postgresql", type="sql")
    unlinked = []
    errors = []
    for cid in campaign_ids:
        try:
            with conn.session as session:
                session.execute(
                    text(
                        'UPDATE smart_lead_campaigns SET "platformOrganizationId" = NULL WHERE "campaignId" = :cid'
                    ),
                    {"cid": str(cid)},
                )
                session.commit()
            unlinked.append(cid)
        except Exception as e:
            errors.append(f"Campaign {cid}: {e}")
    return {"unlinked": unlinked, "errors": errors}


def pause_campaigns_now(org_ids: list[str]) -> dict[str, list]:
    """Pause all Smartlead campaigns for the given orgs and unlink them."""
    from clients.smartlead.index import update_campaign_status

    campaigns_by_org = get_campaign_ids_for_orgs(org_ids)
    paused = []
    errors = []
    all_campaign_ids = []
    for org_id, campaign_ids in campaigns_by_org.items():
        all_campaign_ids.extend(campaign_ids)
        for cid in campaign_ids:
            try:
                update_campaign_status(cid, "PAUSED")
                paused.append(cid)
            except Exception as e:
                errors.append(f"Campaign {cid}: {e}")

    # Unlink campaigns from org
    unlink_result = unlink_campaigns_from_org(all_campaign_ids)
    errors.extend(unlink_result["errors"])

    return {"paused": paused, "unlinked": unlink_result["unlinked"], "errors": errors}


st.title("Pause Platform Organizations")

orgs = get_active_organizations()

# Create a multiselect dropdown for organization selection
org_names = [f"{org['name']} (ID: {org['id']})" for org in orgs]
selected_orgs = st.multiselect(
    "Select organizations to pause",
    options=org_names,
    help="Search and select one or more organizations",
)

# Extract org IDs and names from selected items
selected_org_ids = []
selected_org_names = []
if selected_orgs:
    for selected in selected_orgs:
        org_name = selected.split(" (ID: ")[0]
        org_id = selected.split("ID: ")[1].rstrip(")")
        selected_org_ids.append(org_id)
        selected_org_names.append(org_name)

    st.write(f"Selected {len(selected_org_ids)} organization(s)")
    st.caption("; ".join(selected_org_names))

# Campaign pause options
st.divider()
st.subheader("Campaign Handling")
pause_option = st.radio(
    "When should Smartlead campaigns be paused?",
    options=[
        "Pause campaigns immediately",
        "Schedule pause for a future date",
        "Don't pause campaigns",
    ],
    index=0,
)

scheduled_date = None
if pause_option == "Schedule pause for a future date":
    scheduled_date = st.date_input(
        "Pause campaigns on",
        value=date.today() + timedelta(days=30),
        min_value=date.today() + timedelta(days=1),
        help="Campaigns will be automatically paused on this date (subscription end date)",
    )

confirm = st.checkbox(
    "I understand this will mark the selected organizations as churned"
)

if st.button("Pause organizations", disabled=not confirm or not selected_orgs):
    # 1. Mark orgs as churned in DB
    updated = pause_platform_organizations(org_ids=selected_org_ids)
    st.success(f"Marked {updated} organization(s) as churned")

    # 2. Handle campaigns
    st.divider()
    if pause_option == "Pause campaigns immediately":
        st.subheader("Pausing Smartlead campaigns...")
        result = pause_campaigns_now(selected_org_ids)
        if result["paused"]:
            st.success(f"Paused {len(result['paused'])} campaign(s)")
        if result["unlinked"]:
            st.success(f"Unlinked {len(result['unlinked'])} campaign(s) from org")
        if result["errors"]:
            for err in result["errors"]:
                st.error(err)

    elif pause_option == "Schedule pause for a future date" and scheduled_date:
        st.subheader("Scheduling campaign pauses...")
        campaigns_by_org = get_campaign_ids_for_orgs(selected_org_ids)
        count = add_scheduled_pauses(
            selected_org_ids, selected_org_names, campaigns_by_org, scheduled_date
        )
        st.success(
            f"Scheduled {count} campaign(s) to pause on {scheduled_date.isoformat()}"
        )

    else:
        st.info("Campaigns left running (no pause action taken)")

# --- Show pending scheduled pauses ---
st.divider()
st.subheader("Pending Scheduled Pauses")
try:
    pending = load_scheduled_pauses()
    if pending:
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
    else:
        st.caption("No scheduled pauses pending.")
except Exception:
    st.caption("Could not load scheduled pauses.")
