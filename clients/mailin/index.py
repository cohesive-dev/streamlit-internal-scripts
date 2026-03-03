"""MailIn API client."""

import requests
import time
import streamlit as st


MAILIN_BASE = "https://api.mailin.ai/api/v1/public"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {st.secrets['MAILIN_TOKEN']}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def transfer_or_find_domain(domain_name: str) -> dict:
    """
    Transfer a domain to MailIn via API. If the API rejects it, check if it
    already exists (may have been transferred via the MailIn dashboard).
    Returns domain dict with id, name, name_servers.
    """
    # First check if domain already exists in MailIn
    existing = find_domain_by_name(domain_name)
    if existing:
        return existing

    # Try API transfer
    resp = requests.post(
        f"{MAILIN_BASE}/domains/transfer",
        headers=_headers(),
        json={"domain_name": domain_name},
        timeout=30,
    )

    if resp.ok:
        # Transfer API returns {message, name_servers} but no id.
        # Look up the domain by name to get the full record.
        # Retry a few times since it may take a moment to appear.
        transfer_data = resp.json()
        for attempt in range(5):
            time.sleep(2)
            domain_info = find_domain_by_name(domain_name)
            if domain_info:
                return domain_info

        # Fallback: return what we have, synthesize name_servers string
        ns = transfer_data.get("name_servers", [])
        raise ValueError(
            f"Transfer succeeded for '{domain_name}' but domain not found in listing after retries. "
            f"Nameservers: {ns}. Try again in a moment."
        )

    # API transfer failed — surface the error
    try:
        err = resp.json()
        errors = err.get("errors", {}).get("domain_name", [])
        msg = errors[0] if errors else resp.text
    except Exception:
        msg = resp.text
    raise ValueError(f"Transfer failed for '{domain_name}': {msg}")


def find_domain_by_name(domain_name: str) -> dict | None:
    """Look up a domain by name. Returns domain dict or None."""
    resp = requests.get(
        f"{MAILIN_BASE}/domains",
        headers=_headers(),
        params={"per_page": 100, "name": domain_name},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    for d in data["data"]:
        if d["name"] == domain_name:
            return d
    return None


def get_domain(domain_id: int) -> dict:
    """Get domain status. Check status=='1' and name_server_status=='1' for active."""
    resp = requests.get(
        f"{MAILIN_BASE}/domains/{domain_id}",
        headers=_headers(),
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def create_mailboxes(domain_id: int, mailboxes: list[dict]) -> dict:
    """Create mailboxes on a domain. Returns dict with uuid for async job polling."""
    resp = requests.post(
        f"{MAILIN_BASE}/mailboxes",
        headers=_headers(),
        json={"domain_id": domain_id, "mailboxes": mailboxes},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def get_mailbox_job_status(uuid: str) -> dict:
    """Poll mailbox creation job. Status: 'completed'/'1' = done, 'failed' = error."""
    resp = requests.get(
        f"{MAILIN_BASE}/mailboxes/status/{uuid}",
        headers=_headers(),
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def forward_domain(domain_id: int, forward_to: str) -> dict:
    """Forward a domain to another domain."""
    resp = requests.post(
        f"{MAILIN_BASE}/domains/forward",
        headers=_headers(),
        json={"domain_id": domain_id, "forward_to": forward_to},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def get_mailboxes_for_domain(domain_id: int) -> list[dict]:
    """Fetch all mailboxes for a domain (paginated)."""
    all_mailboxes = []
    page = 1
    while True:
        resp = requests.get(
            f"{MAILIN_BASE}/mailboxes",
            headers=_headers(),
            params={"per_page": 100, "page": page},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        for m in data["data"]:
            if m["domain_id"] == domain_id:
                all_mailboxes.append(m)
        if page >= data.get("last_page", 1):
            break
        page += 1
    return all_mailboxes
