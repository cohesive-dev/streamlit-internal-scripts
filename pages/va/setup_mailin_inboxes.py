"""
Set Up MailIn Inboxes — Full pipeline:
Transfer domains → Set NS → Poll activation → Create mailboxes → Export to Smartlead
"""

import streamlit as st
import pandas as pd
import time
import random

from clients.mailin.index import (
    transfer_or_find_domain,
    get_domain,
    create_mailboxes,
    get_mailbox_job_status,
    forward_domain,
)
from clients.namecheap.index import get_client_ip, set_custom_nameservers
from clients.smartlead.index import query_smartlead

# ─── Constants ────────────────────────────────────────────────────────────────

PERSONA_POOL = [
    {"first": "Emily", "last": "Parker"},
    {"first": "Ashley", "last": "Bennett"},
    {"first": "Lauren", "last": "Hayes"},
    {"first": "Megan", "last": "Collins"},
    {"first": "Natalie", "last": "Brooks"},
    {"first": "Madison", "last": "Reed"},
    {"first": "Hannah", "last": "Foster"},
    {"first": "Rachel", "last": "Turner"},
    {"first": "Caitlin", "last": "Morgan"},
    {"first": "Chloe", "last": "Whitman"},
]
SMTP_HOST = "mail.getcohesiveaihq.biz"
SMTP_PORT = 465
IMAP_HOST = "mail.getcohesiveaihq.biz"
IMAP_PORT = 993

POLL_INTERVAL = 30  # seconds between activation checks
POLL_MAX_WAIT = 1200  # 20 minutes max
MAILBOX_JOB_TIMEOUT = 300  # 5 minutes per mailbox job

# ─── Session State Defaults ───────────────────────────────────────────────────

ss = st.session_state
for key, default in [
    ("mailin_phase", "input"),
    ("mailin_domains_input", ""),
    ("mailin_transferred", []),
    ("mailin_ns_results", []),
    ("mailin_activated", []),
    ("mailin_pending", []),
    ("mailin_mailbox_results", []),
    ("mailin_smartlead_results", []),
    ("mailin_inbox_count", 3),
    ("mailin_name_mode", "Random names"),
    ("mailin_custom_names", {}),  # {domain: {"first": ..., "last": ...}}
    ("mailin_forwarding", {}),  # {domain: "forward_to" or ""}
    ("mailin_log", []),
]:
    ss.setdefault(key, default)

# ─── UI ───────────────────────────────────────────────────────────────────────

st.title("Set Up MailIn Inboxes")


def add_log(msg: str):
    ss.mailin_log.append(msg)


def reset_state():
    for key in [k for k in ss.keys() if k.startswith("mailin_")]:
        del ss[key]


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 1: Domain Input
# ═══════════════════════════════════════════════════════════════════════════════

if ss.mailin_phase == "input":
    st.subheader("Step 1: Enter Domains")
    domains_text = st.text_area(
        "Paste domain names (one per line)",
        value=ss.mailin_domains_input,
        height=200,
        placeholder="example1.com\nexample2.org\nexample3.biz",
    )

    st.subheader("Inbox Options")
    col_a, col_b = st.columns(2)
    with col_a:
        inbox_count = st.radio("Inboxes per domain", [2, 3], index=1, horizontal=True)
    with col_b:
        name_mode = st.radio("Name mode", ["Random names", "Custom name"], horizontal=True)

    # Show per-domain name inputs when custom mode is selected
    parsed_domains = [d.strip() for d in domains_text.strip().splitlines() if d.strip()]
    custom_names = {}

    if name_mode == "Custom name":
        if inbox_count == 2:
            st.caption("Emails per domain: `first@domain`, `first.last@domain`")
        else:
            st.caption("Emails per domain: `first@domain`, `first.last@domain`, `flast@domain`")

        if parsed_domains:
            st.divider()
            for domain in parsed_domains:
                col_d, col_f, col_l = st.columns([2, 1, 1])
                with col_d:
                    st.text(domain)
                with col_f:
                    first = st.text_input("First", key=f"first_{domain}", label_visibility="collapsed", placeholder="First name")
                with col_l:
                    last = st.text_input("Last", key=f"last_{domain}", label_visibility="collapsed", placeholder="Last name")
                custom_names[domain] = {"first": first.strip(), "last": last.strip()}
        else:
            st.info("Enter domains above to configure names.")

    # Domain forwarding config
    st.subheader("Domain Forwarding")
    st.caption("Each domain must be forwarded to a target domain (bare domain only, e.g. `maidthis.com`).")
    forwarding = {}
    if parsed_domains:
        for domain in parsed_domains:
            col_d, col_fwd = st.columns([1, 2])
            with col_d:
                st.text(domain)
            with col_fwd:
                fwd = st.text_input(
                    "Forward to",
                    key=f"fwd_{domain}",
                    label_visibility="collapsed",
                    placeholder="e.g. maidthis.com",
                )
                # Strip to bare domain: remove protocol, paths, trailing slashes
                cleaned = fwd.strip().lower()
                for prefix in ("https://", "http://"):
                    if cleaned.startswith(prefix):
                        cleaned = cleaned[len(prefix):]
                cleaned = cleaned.split("/")[0].strip()
                forwarding[domain] = cleaned

    if st.button("Start Setup", type="primary"):
        if not parsed_domains:
            st.error("Please enter at least one domain.")
        else:
            # Validate forwarding
            missing_fwd = [d for d in parsed_domains if not forwarding.get(d)]
            if missing_fwd:
                st.error(f"Missing forwarding domain for: {', '.join(missing_fwd)}")
            elif name_mode == "Custom name":
                # Validate all names are filled
                missing = [d for d, n in custom_names.items() if not n["first"] or not n["last"]]
                if missing:
                    st.error(f"Missing names for: {', '.join(missing)}")
                else:
                    ss.mailin_domains_input = domains_text
                    ss.mailin_inbox_count = inbox_count
                    ss.mailin_name_mode = name_mode
                    ss.mailin_custom_names = custom_names
                    ss.mailin_forwarding = forwarding
                    ss.mailin_phase = "running"
                    ss.mailin_log = []
                    st.rerun()
            else:
                ss.mailin_domains_input = domains_text
                ss.mailin_inbox_count = inbox_count
                ss.mailin_name_mode = name_mode
                ss.mailin_custom_names = {}
                ss.mailin_forwarding = forwarding
                ss.mailin_phase = "running"
                ss.mailin_log = []
                st.rerun()

# ═══════════════════════════════════════════════════════════════════════════════
# STEPS 2-6: Run Pipeline
# ═══════════════════════════════════════════════════════════════════════════════

if ss.mailin_phase == "running":
    domains = [d.strip() for d in ss.mailin_domains_input.strip().splitlines() if d.strip()]

    # ── Phase 1: Transfer to MailIn ───────────────────────────────────────────
    st.subheader("Step 2: Transferring Domains to MailIn")
    transfer_progress = st.progress(0)
    transfer_status = st.empty()

    transferred = []
    transfer_errors = []

    for i, domain_name in enumerate(domains):
        transfer_status.text(f"Transferring {domain_name}...")
        try:
            result = transfer_or_find_domain(domain_name)
            transferred.append({
                "name": result.get("name", domain_name),
                "id": result["id"],
                "name_servers": result.get("name_servers", ""),
            })
            add_log(f"Transferred: {domain_name} (ID {result['id']})")
        except Exception as e:
            transfer_errors.append({"name": domain_name, "error": str(e)})
            add_log(f"FAIL transfer {domain_name}: {e}")
        transfer_progress.progress((i + 1) / len(domains))
        time.sleep(0.5)

    ss.mailin_transferred = transferred

    if transfer_errors:
        st.warning(f"{len(transfer_errors)} domain(s) failed to transfer:")
        st.dataframe(pd.DataFrame(transfer_errors), use_container_width=True)
    st.success(f"Transferred {len(transferred)}/{len(domains)} domains")

    if not transferred:
        st.error("No domains transferred. Cannot continue.")
        if st.button("Back to Input"):
            ss.mailin_phase = "input"
            st.rerun()
        st.stop()

    # ── Phase 2: Set Nameservers at Namecheap ─────────────────────────────────
    st.subheader("Step 3: Setting Nameservers at Namecheap")
    ns_progress = st.progress(0)
    ns_status = st.empty()

    ns_status.text("Fetching public IP...")
    client_ip = get_client_ip()
    add_log(f"Client IP: {client_ip}")

    ns_results = []
    for i, domain in enumerate(transferred):
        ns = domain["name_servers"]
        if not ns:
            ns_results.append({**domain, "ns_ok": False, "ns_msg": "No nameservers assigned"})
            add_log(f"SKIP NS {domain['name']}: no nameservers")
        else:
            ok, msg = set_custom_nameservers(domain["name"], ns, client_ip)
            ns_results.append({**domain, "ns_ok": ok, "ns_msg": msg})
            add_log(f"NS {'OK' if ok else 'FAIL'} {domain['name']}: {msg}")
            time.sleep(1.5)  # Namecheap rate limit

        ns_status.text(f"Set NS for {domain['name']} — {'OK' if ns_results[-1]['ns_ok'] else 'FAIL'}")
        ns_progress.progress((i + 1) / len(transferred))

    ss.mailin_ns_results = ns_results
    ns_succeeded = [d for d in ns_results if d["ns_ok"]]
    ns_failed = [d for d in ns_results if not d["ns_ok"]]

    if ns_failed:
        st.warning(f"{len(ns_failed)} domain(s) failed NS setting:")
        st.dataframe(
            pd.DataFrame([{"Domain": d["name"], "Error": d["ns_msg"]} for d in ns_failed]),
            use_container_width=True,
        )
    st.success(f"Nameservers set for {len(ns_succeeded)}/{len(transferred)} domains")

    if not ns_succeeded:
        st.error("No nameservers set. Cannot continue.")
        if st.button("Back to Input"):
            ss.mailin_phase = "input"
            st.rerun()
        st.stop()

    # ── Phase 3: Poll for Activation ──────────────────────────────────────────
    st.subheader("Step 4: Waiting for Domain Activation")
    st.info("Domains typically activate in 5-20 minutes depending on TLD.")
    poll_progress = st.progress(0)
    poll_status = st.empty()

    pending = {d["id"]: d["name"] for d in ns_succeeded}
    activated = []
    start_time = time.time()
    total_domains = len(pending)

    while pending and (time.time() - start_time) < POLL_MAX_WAIT:
        still_pending = {}
        for did, dname in list(pending.items()):
            try:
                d = get_domain(did)
                if str(d.get("status")) == "1" and str(d.get("name_server_status")) == "1":
                    activated.append({"id": did, "name": dname})
                    add_log(f"ACTIVATED: {dname}")
                else:
                    still_pending[did] = dname
            except Exception as e:
                still_pending[did] = dname
                add_log(f"Poll error {dname}: {e}")
            time.sleep(0.5)  # MailIn rate limit

        pending = still_pending
        done_count = total_domains - len(pending)
        elapsed = int(time.time() - start_time)
        poll_progress.progress(done_count / total_domains)
        poll_status.text(
            f"{done_count}/{total_domains} activated | {len(pending)} pending | {elapsed}s elapsed"
        )

        if pending:
            time.sleep(POLL_INTERVAL)

    # Any remaining are timed out
    pending_list = [{"id": did, "name": dname} for did, dname in pending.items()]
    ss.mailin_activated = activated
    ss.mailin_pending = pending_list

    st.success(f"{len(activated)} domain(s) activated")
    if pending_list:
        st.warning(
            f"{len(pending_list)} domain(s) still pending after {POLL_MAX_WAIT // 60} min: "
            + ", ".join(d["name"] for d in pending_list)
        )

    if not activated:
        st.error("No domains activated. Cannot continue.")
        if st.button("Back to Input"):
            ss.mailin_phase = "input"
            st.rerun()
        st.stop()

    # ── Phase 3.5: Domain Forwarding ──────────────────────────────────────────
    fwd_config = ss.mailin_forwarding
    domains_to_forward = {d["name"]: d["id"] for d in activated if fwd_config.get(d["name"])}
    if domains_to_forward:
        st.subheader("Step 4.5: Setting Up Domain Forwarding")
        fwd_progress = st.progress(0)
        fwd_status = st.empty()
        fwd_total = len(domains_to_forward)

        for idx, (dname, did) in enumerate(domains_to_forward.items()):
            forward_to = fwd_config[dname]
            fwd_status.text(f"Forwarding {dname} → {forward_to}...")
            try:
                forward_domain(did, forward_to)
                add_log(f"Forwarding OK: {dname} → {forward_to}")
            except Exception as e:
                add_log(f"Forwarding FAIL: {dname} → {forward_to}: {e}")
                st.warning(f"Failed to forward {dname}: {e}")
            fwd_progress.progress((idx + 1) / fwd_total)
            time.sleep(0.5)

        st.success(f"Forwarding configured for {fwd_total} domain(s)")
    else:
        add_log("No domain forwarding configured — skipping")

    # ── Phase 4: Create Mailboxes ─────────────────────────────────────────────
    st.subheader("Step 5: Creating Mailboxes")
    mb_progress = st.progress(0)
    mb_status = st.empty()

    inbox_count = ss.mailin_inbox_count
    name_mode = ss.mailin_name_mode

    mailbox_results = []
    for i, domain in enumerate(activated):
        mb_status.text(f"Creating mailboxes for {domain['name']}...")

        if name_mode == "Custom name":
            names = ss.mailin_custom_names.get(domain["name"], {})
            first = names.get("first", "")
            last = names.get("last", "")
            display_name = f"{first} {last}"
            password = f"Cohesive2026{first[:2].title()}"
            # Email variations in order: first@, first.last@, flast@
            variations = [
                f"{first.lower()}@{domain['name']}",
                f"{first.lower()}.{last.lower()}@{domain['name']}",
                f"{first[0].lower()}{last.lower()}@{domain['name']}",
            ]
            mailboxes_spec = [
                {"username": variations[j], "name": display_name, "password": password}
                for j in range(inbox_count)
            ]
        else:
            # Random personas
            personas = random.sample(PERSONA_POOL, inbox_count)
            mailboxes_spec = [
                {
                    "username": f"{p['first'].lower()}@{domain['name']}",
                    "name": f"{p['first']} {p['last']}",
                    "password": f"Cohesive2026{p['first'][:2].title()}",
                }
                for p in personas
            ]

        try:
            result = create_mailboxes(domain["id"], mailboxes_spec)
            uuid = result.get("uuid") or result.get("data", {}).get("uuid")

            if uuid:
                # Poll for job completion
                job_start = time.time()
                job_done = False
                while (time.time() - job_start) < MAILBOX_JOB_TIMEOUT:
                    status_data = get_mailbox_job_status(uuid)
                    status = status_data.get("status") or status_data.get("data", {}).get("status")
                    if status in ("completed", "1"):
                        mailbox_results.append({
                            "domain": domain["name"],
                            "domain_id": domain["id"],
                            "status": "ok",
                            "mailboxes": mailboxes_spec,
                        })
                        add_log(f"Mailboxes created: {domain['name']}")
                        job_done = True
                        break
                    if status == "failed":
                        mailbox_results.append({
                            "domain": domain["name"],
                            "domain_id": domain["id"],
                            "status": "failed",
                            "mailboxes": [],
                        })
                        add_log(f"Mailbox job failed: {domain['name']}")
                        job_done = True
                        break
                    time.sleep(5)

                if not job_done:
                    mailbox_results.append({
                        "domain": domain["name"],
                        "domain_id": domain["id"],
                        "status": "timeout",
                        "mailboxes": mailboxes_spec,
                    })
                    add_log(f"Mailbox job timeout: {domain['name']} (may complete in background)")
            else:
                mailbox_results.append({
                    "domain": domain["name"],
                    "domain_id": domain["id"],
                    "status": "error",
                    "mailboxes": [],
                })
                add_log(f"Mailbox creation error {domain['name']}: no UUID returned")
        except Exception as e:
            mailbox_results.append({
                "domain": domain["name"],
                "domain_id": domain["id"],
                "status": "error",
                "mailboxes": [],
            })
            add_log(f"Mailbox error {domain['name']}: {e}")

        mb_progress.progress((i + 1) / len(activated))
        time.sleep(1)

    ss.mailin_mailbox_results = mailbox_results
    ok_count = sum(1 for r in mailbox_results if r["status"] in ("ok", "timeout"))
    fail_count = sum(1 for r in mailbox_results if r["status"] not in ("ok", "timeout"))
    st.success(f"Mailboxes created for {ok_count} domain(s), {fail_count} failed")

    # ── Phase 5: Export to Smartlead ──────────────────────────────────────────
    st.subheader("Step 6: Exporting to Smartlead")
    # Collect all mailboxes from successful + timeout domains (timeout jobs usually complete)
    export_domains = [r for r in mailbox_results if r["status"] in ("ok", "timeout") and r["mailboxes"]]
    all_mailboxes = []
    for r in export_domains:
        all_mailboxes.extend(r["mailboxes"])

    sl_progress = st.progress(0)
    sl_status = st.empty()

    smartlead_results = []
    for i, mb in enumerate(all_mailboxes):
        sl_status.text(f"Exporting {mb['username']}...")
        payload = {
            "from_name": mb["name"],
            "from_email": mb["username"],
            "user_name": mb["username"],
            "password": mb["password"],
            "smtp_host": SMTP_HOST,
            "smtp_port": SMTP_PORT,
            "imap_host": IMAP_HOST,
            "imap_port": IMAP_PORT,
            "max_email_per_day": 30,
            "warmup_enabled": True,
            "total_warmup_per_day": 5,
            "daily_rampup": 1,
        }
        try:
            resp = query_smartlead("email-accounts/save", "POST", body=payload)
            # ID may be at resp["id"] or resp["data"]["id"]
            sl_id = resp.get("id") or (resp.get("data", {}) or {}).get("id")
            add_log(f"Smartlead OK: {mb['username']} (ID {sl_id}) raw={resp}")
            smartlead_results.append({
                "email": mb["username"],
                "smartlead_id": sl_id,
                "ok": True,
            })
        except Exception as e:
            smartlead_results.append({
                "email": mb["username"],
                "smartlead_id": None,
                "ok": False,
                "error": str(e),
            })
            add_log(f"Smartlead FAIL: {mb['username']}: {e}")
        sl_progress.progress((i + 1) / len(all_mailboxes))
        time.sleep(0.5)

    ss.mailin_smartlead_results = smartlead_results
    sl_ok = sum(1 for r in smartlead_results if r["ok"])
    sl_fail = sum(1 for r in smartlead_results if not r["ok"])
    st.success(f"Smartlead export: {sl_ok} success, {sl_fail} failed")

    # ── Done ──────────────────────────────────────────────────────────────────
    ss.mailin_phase = "done"
    st.rerun()

# ═══════════════════════════════════════════════════════════════════════════════
# DONE: Summary
# ═══════════════════════════════════════════════════════════════════════════════

if ss.mailin_phase == "done":
    st.subheader("Setup Complete")

    # Summary table
    rows = []
    for r in ss.mailin_smartlead_results:
        rows.append({
            "Email": r["email"],
            "Smartlead ID": r.get("smartlead_id", ""),
            "Status": "OK" if r["ok"] else r.get("error", "Failed"),
        })
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True)

    # Counts
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Transferred", len(ss.mailin_transferred))
    col2.metric("Activated", len(ss.mailin_activated))
    col3.metric(
        "Mailboxes",
        sum(1 for r in ss.mailin_mailbox_results if r["status"] in ("ok", "timeout")) * ss.mailin_inbox_count,
    )
    col4.metric("In Smartlead", sum(1 for r in ss.mailin_smartlead_results if r["ok"]))

    # Pending domains warning
    if ss.mailin_pending:
        st.warning(
            "Pending domains (not activated in time): "
            + ", ".join(d["name"] for d in ss.mailin_pending)
        )

    # Log expander
    with st.expander("Full Log", expanded=False):
        for msg in ss.mailin_log:
            st.text(msg)

    if st.button("Reset for New Run"):
        reset_state()
        st.rerun()
