"""Namecheap API client."""

import requests
import time


def set_custom_nameservers(
    domain_name: str,
    nameservers: str,
    retries: int = 3,
) -> tuple[bool, str]:
    """
    Set custom nameservers for a domain via local API.
    Returns (success, message).
    """
    url = "https://extension.cohesiveapp.com/api/nameservers"
    payload = {
        "domainName": domain_name,
        "nameservers": nameservers,
    }

    for attempt in range(retries):
        try:
            resp = requests.post(url, json=payload, timeout=15)
            if resp.status_code == 200 and resp.json().get("success"):
                return True, "OK"
            else:
                return False, f"HTTP {resp.status_code}: {resp.text}"
        except requests.RequestException as e:
            if attempt < retries - 1:
                time.sleep(3)
                continue
            return False, f"Error after {retries} retries: {e}"
