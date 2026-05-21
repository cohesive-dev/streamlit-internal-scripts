import json
from datetime import date, timedelta

import streamlit as st
from sqlalchemy import text

from azure.storage.blob import ContentSettings
from clients.azure_blob_storage.index import get_or_create_blob_service_client

SCHEDULED_PAUSES_BLOB = "scheduled-campaign-pauses.json"

# Pre-warmed inbox tags (canonical Smartlead tag IDs).
# These are the AUTHORITATIVE signal for "this inbox came from the shared pool."
# Customer-dedicated MailIn inboxes (provisioned via setup_mailin_inboxes*.py)
# share the mail.getcohesiveaihq.biz host and SMTP type with pool inboxes —
# so host/type cannot be used as fallback without false positives that would
# detach customer-owned inboxes on churn.
TAG_PREWARMED_POOL = 258486  # active, attach-eligible pool
TAG_PREWARMED_AT_CAP = 371065  # pre-warmed at MAX_CAMPAIGNS=2
TAG_LEGACY_MAILIN_PREWARMED = 318575  # older MailIn pre-warmed
PREWARMED_TAG_IDS = {
    TAG_PREWARMED_POOL,
    TAG_PREWARMED_AT_CAP,
    TAG_LEGACY_MAILIN_PREWARMED,
}


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


def _is_prewarmed(tags: list[dict]) -> bool:
    """Identify a pre-warmed inbox by tag.

    Tags are the only safe signal: customer-dedicated MailIn inboxes use
    the same SMTP type and host as pool inboxes, so type/host fallbacks
    would false-positive and detach customer-owned inboxes on churn.

    Accepts both Smartlead tag-list response shapes — `{tag_id, tag_name}`
    (older) and `{id, name}` (newer Mintlify docs). Tag IDs may come back
    as int or numeric string; coerce before comparing.
    """
    for t in tags or []:
        raw = t.get("tag_id") if t.get("tag_id") is not None else t.get("id")
        if raw is None:
            continue
        try:
            tid = int(raw)
        except (TypeError, ValueError):
            continue
        if tid in PREWARMED_TAG_IDS:
            return True
    return False


def _apply_tag_batched(
    account_ids: list[int],
    tag_id: int,
    op_method: str,
    op_name: str,
) -> tuple[list[int], list[int], list[str]]:
    """Apply tag-mapping (POST/DELETE) per 25-batch. Track per-batch outcomes
    so a mid-failure leaves us with the exact set of IDs that still need
    repair, not a swallow-and-continue.

    Returns (succeeded_ids, failed_ids, error_msgs).
    """
    from clients.smartlead.index import query_smartlead

    succeeded: list[int] = []
    failed: list[int] = []
    msgs: list[str] = []
    for i in range(0, len(account_ids), 25):
        batch = account_ids[i : i + 25]
        try:
            query_smartlead(
                endpoint="email-accounts/tag-mapping",
                method=op_method,
                body={"email_account_ids": batch, "tag_ids": [tag_id]},
            )
            succeeded.extend(batch)
        except Exception as e:
            failed.extend(batch)
            msgs.append(
                f"{op_name} batch {i // 25 + 1} ({len(batch)} inbox(es)) failed: {e}"
            )
    return succeeded, failed, msgs


def reclaim_prewarmed_inboxes_for_campaigns(campaign_ids: list[int]) -> dict:
    """Detach pre-warmed inboxes from the given campaigns and restore pool tags.

    For each campaign: fetch attached accounts → check tag-list →
    detach the pre-warmed subset. After all detaches, on the union of detached
    accounts: remove TAG_PREWARMED_AT_CAP (they're no longer at cap) and add
    TAG_PREWARMED_POOL (idempotent POST). Both tag operations are batched
    per-25 so a mid-loop failure still surfaces the exact IDs that need
    manual repair.

    Returns {per_campaign, total_inboxes, errors, needs_pool_tag_repair,
    needs_at_cap_tag_repair}. The two repair lists are (id, email) pairs
    for inboxes that came off a campaign but where the tag update failed:
    `needs_pool_tag_repair` won't be auto-attached until the pool tag is
    restored; `needs_at_cap_tag_repair` still carries the at-cap tag and
    will be filtered out of the active pool until the tag is removed.
    """
    from clients.smartlead.index import (
        get_campaign_email_accounts,
        detach_email_accounts_from_campaign,
        get_tags_for_emails,
    )

    per_campaign: dict[int, list[str]] = {}
    all_detached_ids: set[int] = set()
    id_to_email: dict[int, str] = {}
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
        # Fail closed: without a reliable tag map, _is_prewarmed would return
        # False for every account and we'd detach nothing. That's already
        # safe, but we surface the error explicitly and skip the campaign
        # to match the Special-Ignore pattern in cohesive-slack-bots.
        try:
            tags_by_id = get_tags_for_emails(emails)
        except Exception as e:
            errors.append(
                f"Campaign {cid} tag-list failed ({e}); skipping detach for this campaign"
            )
            continue

        prewarmed_ids: list[int] = []
        for a in accounts:
            aid = a.get("id")
            if not isinstance(aid, int):
                continue
            if _is_prewarmed(tags_by_id.get(aid, [])):
                prewarmed_ids.append(aid)
                id_to_email[aid] = a.get("from_email") or str(aid)

        if not prewarmed_ids:
            continue

        # Batch detach at 25 — detach endpoint cap is undocumented; mirror
        # the tag-mapping cap defensively. Track which batches succeeded
        # so post-detach tag updates only target IDs that actually came off.
        detached_this_campaign: list[int] = []
        for i in range(0, len(prewarmed_ids), 25):
            batch = prewarmed_ids[i : i + 25]
            try:
                detach_email_accounts_from_campaign(cid, batch)
                detached_this_campaign.extend(batch)
            except Exception as e:
                errors.append(
                    f"Campaign {cid} detach batch {i // 25 + 1} "
                    f"({len(batch)} inbox(es)): {e}"
                )

        if detached_this_campaign:
            per_campaign[cid] = [
                id_to_email.get(aid, str(aid)) for aid in detached_this_campaign
            ]
            all_detached_ids.update(detached_this_campaign)

    detached_ids = sorted(all_detached_ids)
    needs_pool_tag_repair: list[tuple[int, str]] = []
    needs_at_cap_tag_repair: list[tuple[int, str]] = []
    if detached_ids:
        _, at_cap_failed, at_cap_msgs = _apply_tag_batched(
            detached_ids, TAG_PREWARMED_AT_CAP, "DELETE", "Remove at-cap tag"
        )
        errors.extend(at_cap_msgs)
        # At-cap tag still attached = inbox stays out of the eligible pool
        # (get_prewarmed_pool filters on it). Symmetric with pool-tag repair.
        needs_at_cap_tag_repair = [
            (aid, id_to_email.get(aid, str(aid))) for aid in at_cap_failed
        ]

        _, pool_failed, pool_msgs = _apply_tag_batched(
            detached_ids, TAG_PREWARMED_POOL, "POST", "Restore pool tag"
        )
        errors.extend(pool_msgs)
        # Inboxes that came off a campaign but didn't get the pool tag back
        # are stranded — surface them prominently for manual repair.
        needs_pool_tag_repair = [
            (aid, id_to_email.get(aid, str(aid))) for aid in pool_failed
        ]

    return {
        "per_campaign": per_campaign,
        "total_inboxes": len(detached_ids),
        "errors": errors,
        "needs_pool_tag_repair": needs_pool_tag_repair,
        "needs_at_cap_tag_repair": needs_at_cap_tag_repair,
    }


def reclaim_prewarmed_for_orgs(org_ids: list[str]) -> dict:
    """Resolve campaigns for the given orgs and reclaim their pre-warmed inboxes."""
    campaigns_by_org = get_campaign_ids_for_orgs(org_ids)
    all_campaign_ids: list[int] = []
    for cids in campaigns_by_org.values():
        all_campaign_ids.extend(cids)
    if not all_campaign_ids:
        return {
            "per_campaign": {},
            "total_inboxes": 0,
            "errors": [],
            "needs_pool_tag_repair": [],
            "needs_at_cap_tag_repair": [],
        }
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
force_pause_on_reclaim_error = st.checkbox(
    "Force pause even if pre-warmed reclaim has errors",
    value=False,
    help=(
        "By default, if reclaim returns any error (tag-list failure, detach "
        "failure, pool-tag restore failure), the org is NOT marked churned "
        "and campaigns are NOT paused — so you can fix the issue and retry "
        "from the same dropdown. Check this to push through known-tolerable "
        "errors and complete the churn anyway."
    ),
)

if st.button("Pause organizations", disabled=not confirm or not selected_orgs):
    # 1. Reclaim pre-warmed inboxes BEFORE flipping the org to paused.
    # If Smartlead errors here and the operator hasn't checked the override,
    # we halt before the DB pause so the org stays active (paused=false)
    # and the operator can retry from the same dropdown.
    st.subheader("Reclaiming pre-warmed inboxes...")
    reclaim = reclaim_prewarmed_for_orgs(selected_org_ids)
    if reclaim["total_inboxes"]:
        tag_ops_clean = (
            not reclaim["needs_pool_tag_repair"]
            and not reclaim["needs_at_cap_tag_repair"]
        )
        detach_summary = (
            f"Detached {reclaim['total_inboxes']} pre-warmed inbox(es) "
            f"across {len(reclaim['per_campaign'])} campaign(s)"
        )
        if tag_ops_clean:
            st.success(
                f"{detach_summary}; restored pool tag, removed at-cap tag."
            )
        else:
            st.warning(
                f"{detach_summary}; tag updates partially failed — see "
                f"manual repair block(s) below."
            )
        with st.expander("Detached inboxes by campaign"):
            for cid, emails in reclaim["per_campaign"].items():
                st.markdown(f"**Campaign {cid}** — {len(emails)} inbox(es)")
                st.caption(", ".join(emails))
    else:
        st.info("No pre-warmed inboxes attached to these orgs' campaigns.")
    for err in reclaim["errors"]:
        st.error(err)
    # Inboxes detached from a campaign but missing the pool tag are orphans
    # — they won't be re-attached by the auto-attach flow until repaired.
    # Surface them prominently with both id and email for manual cleanup.
    if reclaim["needs_pool_tag_repair"]:
        st.error(
            f"MANUAL REPAIR NEEDED — {len(reclaim['needs_pool_tag_repair'])} "
            f"inbox(es) were detached from a campaign but failed to receive "
            f"the pool tag (258486). Re-tag them manually in Smartlead so "
            f"the auto-attach flow can pick them back up:"
        )
        for aid, email in reclaim["needs_pool_tag_repair"]:
            st.code(f"{aid}  {email}")
    # At-cap tag stuck = inbox stays out of the eligible pool until removed.
    if reclaim["needs_at_cap_tag_repair"]:
        st.error(
            f"MANUAL REPAIR NEEDED — {len(reclaim['needs_at_cap_tag_repair'])} "
            f"inbox(es) still carry the at-cap tag (371065) after detach. "
            f"Remove the tag manually in Smartlead so they re-enter the "
            f"eligible pool:"
        )
        for aid, email in reclaim["needs_at_cap_tag_repair"]:
            st.code(f"{aid}  {email}")

    if reclaim["errors"] and not force_pause_on_reclaim_error:
        st.warning(
            "Reclaim returned errors and 'Force pause' is unchecked — "
            "org NOT marked churned and campaigns NOT paused. Fix the "
            "underlying issue and click 'Pause organizations' again, or "
            "check the 'Force pause' box above to push through."
        )
        st.stop()

    # 2. Mark orgs as churned in DB
    st.divider()
    updated = pause_platform_organizations(org_ids=selected_org_ids)
    st.success(f"Marked {updated} organization(s) as churned")

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
