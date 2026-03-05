"""
Set Up MailIn Inboxes — Full pipeline:
Transfer domains → Set NS → Poll activation → Create mailboxes → Export to Smartlead
"""

import streamlit as st
import time
import random
import queue
from concurrent.futures import ThreadPoolExecutor

from clients.mailin.index import (
    transfer_or_find_domain,
    get_domain,
    create_mailboxes,
    get_mailbox_job_status,
    forward_domain,
)
from clients.namecheap.index import set_custom_nameservers
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
    ("mailin_results", []),  # list of per-domain result dicts
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
# Pipeline Step Functions
# ═══════════════════════════════════════════════════════════════════════════════


def step_transfer_domain(domain_name: str) -> dict:
    """Transfer a domain to MailIn (or find existing). Returns domain info dict."""
    result = transfer_or_find_domain(domain_name)
    return {
        "name": result.get("name", domain_name),
        "id": result["id"],
        "name_servers": result.get("name_servers", ""),
    }


def step_set_nameservers(domain: dict) -> dict:
    """Set Namecheap nameservers for a domain. Returns domain dict with ns_ok/ns_msg."""
    ns = domain["name_servers"]
    if not ns:
        return {**domain, "ns_ok": False, "ns_msg": "No nameservers assigned"}
    ok, msg = set_custom_nameservers(domain["name"], ns)
    time.sleep(1.5)  # Namecheap rate limit
    return {**domain, "ns_ok": ok, "ns_msg": msg}


def step_poll_activation(
    domain_id: str,
    domain_name: str,
    logs: list,
    notify,
) -> bool:
    """Poll MailIn until the domain is active or the timeout is reached. Returns True if activated."""
    start = time.time()
    attempt = 0
    while (time.time() - start) < POLL_MAX_WAIT:
        attempt += 1
        elapsed = int(time.time() - start)
        try:
            d = get_domain(domain_id)
            print(d)
            status = str(d.get("status"))
            ns_status = str(d.get("name_server_status"))
            notify(
                2,
                f"⏳ Activating… attempt {attempt} | {elapsed}s elapsed "
                f"(domain={status}, ns={ns_status})",
            )
            if status == "1" and ns_status == "1":
                return True
        except Exception as e:
            logs.append(f"[{domain_name}] Step 3 (Activation): poll error — {e}")
            notify(
                2,
                f"⏳ Activating… attempt {attempt} | {elapsed}s elapsed (poll error: {e})",
            )
        time.sleep(POLL_INTERVAL)
    return False


def step_setup_forwarding(domain_id: str, domain_name: str, forward_to: str) -> None:
    """Configure domain-level catch-all forwarding in MailIn."""
    forward_domain(domain_id, forward_to)


def step_create_mailboxes(
    domain: dict,
    inbox_count: int,
    name_mode: str,
    custom_names: dict,
) -> list:
    """
    Submit a mailbox-creation job for one domain and poll until complete.
    Returns the list of mailbox spec dicts that were created.
    """
    if name_mode == "Custom name":
        names = custom_names.get(domain["name"], {})
        first = names.get("first", "")
        last = names.get("last", "")
        display_name = f"{first} {last}"
        password = f"Cohesive2026{first[:2].title()}"
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
        personas = random.sample(PERSONA_POOL, inbox_count)
        mailboxes_spec = [
            {
                "username": f"{p['first'].lower()}@{domain['name']}",
                "name": f"{p['first']} {p['last']}",
                "password": f"Cohesive2026{p['first'][:2].title()}",
            }
            for p in personas
        ]

    result = create_mailboxes(domain["id"], mailboxes_spec)
    uuid = result.get("uuid") or result.get("data", {}).get("uuid")
    if not uuid:
        raise RuntimeError("No UUID returned from create_mailboxes")

    # Poll job to completion
    job_start = time.time()
    while (time.time() - job_start) < MAILBOX_JOB_TIMEOUT:
        status_data = get_mailbox_job_status(uuid)
        status = status_data.get("status") or status_data.get("data", {}).get("status")
        if status in ("completed", "1"):
            return mailboxes_spec
        if status == "failed":
            raise RuntimeError(f"Mailbox job failed for {domain['name']}")
        time.sleep(5)

    # Return spec optimistically — job may still finish in background
    return mailboxes_spec


def step_export_to_smartlead(mailboxes: list, logs: list) -> list:
    """Add a list of mailboxes to Smartlead. Returns list of result dicts."""
    results = []
    for mb in mailboxes:
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
            sl_id = resp.get("id") or (resp.get("data", {}) or {}).get("id")
            logs.append(f"Smartlead OK: {mb['username']} (ID {sl_id})")
            results.append({"email": mb["username"], "smartlead_id": sl_id, "ok": True})
        except Exception as e:
            logs.append(f"Smartlead FAIL: {mb['username']}: {e}")
            results.append(
                {
                    "email": mb["username"],
                    "smartlead_id": None,
                    "ok": False,
                    "error": str(e),
                }
            )
        time.sleep(0.5)
    return results


# ─── Per-Domain Orchestrator ──────────────────────────────────────────────────


def run_domain_pipeline(
    domain_name: str,
    inbox_count: int,
    name_mode: str,
    custom_names: dict,
    forwarding: dict,
    progress_queue: queue.Queue,
) -> dict:
    """
    Run every pipeline step for a single domain in sequence.
    Safe to call from a background thread — progress events are put into
    progress_queue and consumed by the main thread to update the UI.
    """
    TOTAL_STEPS = 6
    logs: list[str] = []

    def _progress(step: int, msg: str) -> None:
        """Put a progress event; the main thread will apply it to the UI."""
        progress_queue.put(
            {"domain": domain_name, "step": step, "total": TOTAL_STEPS, "msg": msg}
        )

    result = {
        "name": domain_name,
        "transferred": False,
        "ns_ok": False,
        "activated": False,
        "forwarded": False,
        "mailboxes": [],
        "smartlead": [],
        "error": None,
        "logs": logs,
    }

    # ── 1. Transfer to MailIn ─────────────────────────────────────────────────
    _progress(0, "⏳ Transferring to MailIn…")
    try:
        domain = step_transfer_domain(domain_name)
        result["transferred"] = True
        logs.append(f"[{domain_name}] Step 1 (Transfer): OK (ID {domain['id']})")
    except Exception as e:
        logs.append(f"[{domain_name}] Step 1 (Transfer): FAILED — {e}")
        result["error"] = f"Step 1 – Transfer failed: {e}"
        _progress(TOTAL_STEPS, f"❌ Failed at Transfer")
        return result
    _progress(1, "✅ Transferred — setting nameservers…")
    time.sleep(0.5)

    # ── 2. Set Nameservers at Namecheap ───────────────────────────────────────
    try:
        domain = step_set_nameservers(domain)
        result["ns_ok"] = domain["ns_ok"]
        if not domain["ns_ok"]:
            logs.append(
                f"[{domain_name}] Step 2 (Nameservers): FAILED — {domain['ns_msg']}"
            )
            result["error"] = f"Step 2 – Nameservers failed: {domain['ns_msg']}"
            _progress(TOTAL_STEPS, f"❌ Failed at Nameservers")
            return result
        logs.append(f"[{domain_name}] Step 2 (Nameservers): OK")
    except Exception as e:
        logs.append(f"[{domain_name}] Step 2 (Nameservers): FAILED — {e}")
        result["error"] = f"Step 2 – Nameservers error: {e}"
        _progress(TOTAL_STEPS, f"❌ Failed at Nameservers")
        return result
    _progress(2, "✅ Nameservers set — waiting for activation…")

    # ── 3. Poll for Activation ────────────────────────────────────────────────
    logs.append(f"[{domain_name}] Step 3 (Activation): polling…")
    activated = step_poll_activation(domain["id"], domain["name"], logs, _progress)
    result["activated"] = activated
    if not activated:
        logs.append(
            f"[{domain_name}] Step 3 (Activation): TIMED OUT after {POLL_MAX_WAIT // 60} min"
        )
        result["error"] = (
            f"Step 3 – Activation timed out after {POLL_MAX_WAIT // 60} min"
        )
        _progress(TOTAL_STEPS, "❌ Timed out waiting for activation")
        return result
    logs.append(f"[{domain_name}] Step 3 (Activation): OK")
    _progress(3, "✅ Activated — setting up forwarding…")

    # ── 4. Domain Forwarding (optional) ───────────────────────────────────────
    forward_to = forwarding.get(domain_name, "")
    if forward_to:
        try:
            step_setup_forwarding(domain["id"], domain["name"], forward_to)
            result["forwarded"] = True
            logs.append(f"[{domain_name}] Step 4 (Forwarding): OK \u2192 {forward_to}")
        except Exception as e:
            # Non-fatal: log the warning and continue to mailbox creation
            logs.append(
                f"[{domain_name}] Step 4 (Forwarding): WARNING — {e} (continuing)"
            )
    _progress(4, "✅ Forwarding done — creating mailboxes…")

    # ── 5. Create Mailboxes ───────────────────────────────────────────────────
    try:
        mailboxes = step_create_mailboxes(domain, inbox_count, name_mode, custom_names)
        result["mailboxes"] = mailboxes
        logs.append(
            f"[{domain_name}] Step 5 (Mailboxes): OK ({len(mailboxes)} created)"
        )
    except Exception as e:
        logs.append(f"[{domain_name}] Step 5 (Mailboxes): FAILED — {e}")
        result["error"] = f"Step 5 – Mailbox creation failed: {e}"
        _progress(TOTAL_STEPS, "❌ Failed at Mailbox creation")
        return result
    _progress(5, "✅ Mailboxes created — exporting to Smartlead…")
    time.sleep(1)

    # ── 6. Export to Smartlead ────────────────────────────────────────────────
    result["smartlead"] = step_export_to_smartlead(mailboxes, logs)
    sl_ok = sum(1 for s in result["smartlead"] if s["ok"])
    sl_fail = len(result["smartlead"]) - sl_ok
    logs.append(f"[{domain_name}] Step 6 (Smartlead): {sl_ok} OK, {sl_fail} failed")
    _progress(TOTAL_STEPS, f"✅ Done — {sl_ok} mailbox(es) in Smartlead")

    return result


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
        name_mode = st.radio(
            "Name mode", ["Random names", "Custom name"], horizontal=True
        )

    # Show per-domain name inputs when custom mode is selected
    parsed_domains = [d.strip() for d in domains_text.strip().splitlines() if d.strip()]
    custom_names = {}

    if name_mode == "Custom name":
        if inbox_count == 2:
            st.caption("Emails per domain: `first@domain`, `first.last@domain`")
        else:
            st.caption(
                "Emails per domain: `first@domain`, `first.last@domain`, `flast@domain`"
            )

        if parsed_domains:
            st.divider()
            for domain in parsed_domains:
                col_d, col_f, col_l = st.columns([2, 1, 1])
                with col_d:
                    st.text(domain)
                with col_f:
                    first = st.text_input(
                        "First",
                        key=f"first_{domain}",
                        label_visibility="collapsed",
                        placeholder="First name",
                    )
                with col_l:
                    last = st.text_input(
                        "Last",
                        key=f"last_{domain}",
                        label_visibility="collapsed",
                        placeholder="Last name",
                    )
                custom_names[domain] = {"first": first.strip(), "last": last.strip()}
        else:
            st.info("Enter domains above to configure names.")

    # Domain forwarding config
    st.subheader("Domain Forwarding")
    st.caption(
        "Each domain must be forwarded to a target domain (bare domain only, e.g. `maidthis.com`)."
    )
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
                        cleaned = cleaned[len(prefix) :]
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
                missing = [
                    d
                    for d, n in custom_names.items()
                    if not n["first"] or not n["last"]
                ]
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
# STEP 2: Run Pipeline (all domains concurrently)
# ═══════════════════════════════════════════════════════════════════════════════

MAX_PARALLEL_DOMAINS = 5


def _build_results_rows(results: list) -> list:
    return [
        {
            "Domain": r["name"],
            "Transferred": "\u2713" if r["transferred"] else "\u2717",
            "NS Set": "\u2713" if r["ns_ok"] else "\u2717",
            "Activated": "\u2713" if r["activated"] else "\u2717",
            "Forwarded": "\u2713" if r["forwarded"] else "\u2014",
            "Mailboxes": len(r["mailboxes"]),
            "In Smartlead": sum(1 for s in r["smartlead"] if s["ok"]),
            "Error": r.get("error") or "",
        }
        for r in results
    ]


if ss.mailin_phase == "running":
    domains = [
        d.strip() for d in ss.mailin_domains_input.strip().splitlines() if d.strip()
    ]

    st.subheader("Running Pipeline")
    st.caption(
        f"Running up to {MAX_PARALLEL_DOMAINS} domains in parallel. "
        "Failures are isolated — other domains continue unaffected."
    )

    # Pre-create per-domain UI rows on the main thread
    domain_slots: dict[str, dict] = {}
    for d in domains:
        col_name, col_bar, col_status = st.columns([2, 3, 4])
        col_name.markdown(f"**{d}**")
        domain_slots[d] = {
            "progress": col_bar.progress(0.0),
            "status": col_status.empty(),
        }

    st.divider()
    overall_progress = st.progress(0)
    overall_label = st.empty()

    progress_queue: queue.Queue = queue.Queue()
    all_results: list = []
    completed = 0

    with ThreadPoolExecutor(
        max_workers=min(len(domains), MAX_PARALLEL_DOMAINS)
    ) as executor:
        futures = {
            executor.submit(
                run_domain_pipeline,
                domain_name=d,
                inbox_count=ss.mailin_inbox_count,
                name_mode=ss.mailin_name_mode,
                custom_names=ss.mailin_custom_names,
                forwarding=ss.mailin_forwarding,
                progress_queue=progress_queue,
            ): d
            for d in domains
        }

        pending = set(futures)
        while pending:
            # Drain all queued progress events on the main thread (safe for Streamlit UI)
            while True:
                try:
                    event = progress_queue.get_nowait()
                    d = event["domain"]
                    domain_slots[d]["progress"].progress(event["step"] / event["total"])
                    domain_slots[d]["status"].text(event["msg"])
                except queue.Empty:
                    break

            # Collect any futures that finished since last iteration
            done = {f for f in pending if f.done()}
            for f in done:
                pending.discard(f)
                domain_result = f.result()
                ss.mailin_log.extend(domain_result.pop("logs", []))
                all_results.append(domain_result)
                completed += 1
                ss.mailin_results = list(all_results)
                overall_progress.progress(completed / len(domains))
                overall_label.text(f"{completed}/{len(domains)} domains finished")

            if pending:
                time.sleep(0.2)

    # ── Final tally ───────────────────────────────────────────────────────────
    succeeded = [r for r in all_results if not r["error"]]
    failed = [r for r in all_results if r["error"]]

    if succeeded:
        st.success(f"{len(succeeded)} domain(s) completed successfully.")
    if failed:
        st.error(f"{len(failed)} domain(s) failed:")
        for r in failed:
            st.markdown(f"- **{r['name']}** — {r['error']}")

    ss.mailin_phase = "done"
    st.rerun()


if ss.mailin_phase == "done":
    st.subheader("Setup Complete")

    results = ss.mailin_results

    rows = [
        {
            "Email": s["email"],
            "Smartlead ID": s.get("smartlead_id", ""),
            "Status": "OK" if s["ok"] else s.get("error", "Failed"),
        }
        for r in results
        for s in r["smartlead"]
    ]
    if rows:
        st.table(rows)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Transferred", sum(1 for r in results if r["transferred"]))
    col2.metric("Activated", sum(1 for r in results if r["activated"]))
    col3.metric("Mailboxes", sum(len(r["mailboxes"]) for r in results))
    col4.metric("In Smartlead", sum(s["ok"] for r in results for s in r["smartlead"]))

    with st.expander("Per-Domain Summary", expanded=True):
        st.table(_build_results_rows(results))

    with st.expander("Full Log", expanded=False):
        for msg in ss.mailin_log:
            st.text(msg)

    if st.button("Reset for New Run"):
        reset_state()
        st.rerun()
