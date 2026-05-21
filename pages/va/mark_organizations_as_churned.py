import json
from datetime import date, timedelta

import streamlit as st
from sqlalchemy import text

from azure.storage.blob import ContentSettings
from clients.azure_blob_storage.index import get_or_create_blob_service_client

SCHEDULED_PAUSES_BLOB = "scheduled-campaign-pauses.json"

# Pre-warmed inbox tags (canonical Smartlead tag IDs)
TAG_PREWARMED_POOL = 258486  # active, attach-eligible pool
TAG_PREWARMED_AT_CAP = 371065  # pre-warmed at MAX_CAMPAIGNS=2
TAG_LEGACY_MAILIN_PREWARMED = 318575  # older MailIn pre-warmed
PREWARMED_TAG_IDS = {
    TAG_PREWARMED_POOL,
    TAG_PREWARMED_AT_CAP,
    TAG_LEGACY_MAILIN_PREWARMED,
}
# MailIn-hosted inboxes — catches pre-warmed ones that may have lost their tag
PREWARMED_SMTP_HOST = "mail.getcohesiveaihq.biz"


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


def _is_prewarmed(account: dict, tags: list[dict]) -> bool:
    """Identify a pre-warmed inbox by tag, SMTP type, or MailIn host.

    Uses any of:
      - Tag 258486 (Pre-Warmed Pool), 371065 (Pre-Warmed At Cap),
        318575 (legacy MailIn Pre-Warmed)
      - account.type == "SMTP" (catches MailIn inboxes)
      - smtp_host contains mail.getcohesiveaihq.biz (MailIn-hosted fallback)
    """
    if account.get("type") == "SMTP":
        return True
    if PREWARMED_SMTP_HOST in (account.get("smtp_host") or ""):
        return True
    for t in tags or []:
        tid = t.get("tag_id") or t.get("id")
        if tid in PREWARMED_TAG_IDS:
            return True
    return False


def reclaim_prewarmed_inboxes_for_campaigns(campaign_ids: list[int]) -> dict:
    """Detach pre-warmed inboxes from the given campaigns and restore pool tags.

    For each campaign: fetch attached accounts → check tag-list + smtp_host →
    detach the pre-warmed subset. After all detaches, on the union of detached
    accounts: remove TAG_PREWARMED_AT_CAP (they're no longer at cap) and ensure
    TAG_PREWARMED_POOL is present (Smartlead tag-mapping POST is idempotent).

    Returns {per_campaign, total_inboxes, errors}.
    """
    from clients.smartlead.index import (
        get_campaign_email_accounts,
        detach_email_accounts_from_campaign,
        get_tags_for_emails,
        add_tag_to_accounts,
        remove_tag_from_accounts,
    )

    per_campaign: dict[int, list[str]] = {}
    all_detached_ids: set[int] = set()
    errors: list[str] = []

    for cid in campaign_ids:
        try:
            accounts = get_campaign_email_accounts(cid)
        except Exception as e:
            errors.append(f"Campaign {cid} fetch accounts: {e}")
            continue
        if not accounts:
            continue

        emails = [a.get("from_email") for a in accounts if a.get("from_email")]
        try:
            tags_by_id = get_tags_for_emails(emails)
        except Exception as e:
            errors.append(f"Campaign {cid} fetch tags: {e}")
            tags_by_id = {}

        prewarmed_ids: list[int] = []
        prewarmed_emails: list[str] = []
        for a in accounts:
            aid = a.get("id")
            if not isinstance(aid, int):
                continue
            if _is_prewarmed(a, tags_by_id.get(aid, [])):
                prewarmed_ids.append(aid)
                prewarmed_emails.append(a.get("from_email") or str(aid))

        if not prewarmed_ids:
            continue

        try:
            detach_email_accounts_from_campaign(cid, prewarmed_ids)
            per_campaign[cid] = prewarmed_emails
            all_detached_ids.update(prewarmed_ids)
        except Exception as e:
            errors.append(f"Campaign {cid} detach: {e}")

    detached_ids = sorted(all_detached_ids)
    if detached_ids:
        try:
            remove_tag_from_accounts(detached_ids, TAG_PREWARMED_AT_CAP)
        except Exception as e:
            errors.append(f"Remove at-cap tag: {e}")
        try:
            add_tag_to_accounts(detached_ids, TAG_PREWARMED_POOL)
        except Exception as e:
            errors.append(f"Restore pool tag: {e}")

    return {
        "per_campaign": per_campaign,
        "total_inboxes": len(detached_ids),
        "errors": errors,
    }


def reclaim_prewarmed_for_orgs(org_ids: list[str]) -> dict:
    """Resolve campaigns for the given orgs and reclaim their pre-warmed inboxes."""
    campaigns_by_org = get_campaign_ids_for_orgs(org_ids)
    all_campaign_ids: list[int] = []
    for cids in campaigns_by_org.values():
        all_campaign_ids.extend(cids)
    if not all_campaign_ids:
        return {"per_campaign": {}, "total_inboxes": 0, "errors": []}
    return reclaim_prewarmed_inboxes_for_campaigns(all_campaign_ids)


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

    # 2. Reclaim pre-warmed inboxes regardless of pause option. A churned
    # customer shouldn't keep holding shared pool inboxes through the
    # wind-down period; their dedicated inboxes keep the campaign sending
    # in the meantime if it's still running. Runs BEFORE pause/unlink so
    # the DB still resolves campaigns for these orgs.
    st.divider()
    st.subheader("Reclaiming pre-warmed inboxes...")
    reclaim = reclaim_prewarmed_for_orgs(selected_org_ids)
    if reclaim["total_inboxes"]:
        st.success(
            f"Detached {reclaim['total_inboxes']} pre-warmed inbox(es) "
            f"across {len(reclaim['per_campaign'])} campaign(s); "
            f"restored pool tag, removed at-cap tag."
        )
        with st.expander("Detached inboxes by campaign"):
            for cid, emails in reclaim["per_campaign"].items():
                st.markdown(f"**Campaign {cid}** — {len(emails)} inbox(es)")
                st.caption(", ".join(emails))
    else:
        st.info("No pre-warmed inboxes attached to these orgs' campaigns.")
    for err in reclaim["errors"]:
        st.error(err)

    # 3. Handle campaigns
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
