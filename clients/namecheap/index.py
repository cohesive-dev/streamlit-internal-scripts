"""Namecheap API client."""

import requests
import time
import xml.etree.ElementTree as ET
import streamlit as st


NAMECHEAP_URL = "https://api.namecheap.com/xml.response"


def get_client_ip() -> str:
    """Fetch current public IP for Namecheap API whitelisting."""
    resp = requests.get("https://api.ipify.org", timeout=10)
    return resp.text.strip()


def set_custom_nameservers(
    domain_name: str,
    nameservers: str,
    client_ip: str,
    retries: int = 3,
) -> tuple[bool, str]:
    """
    Set custom nameservers for a domain at Namecheap.
    Returns (success, message).
    """
    parts = domain_name.split(".")
    sld = parts[0]
    tld = ".".join(parts[1:])

    params = {
        "ApiUser": st.secrets["NAMECHEAP_USER"],
        "ApiKey": st.secrets["NAMECHEAP_API_KEY"],
        "UserName": st.secrets["NAMECHEAP_USER"],
        "ClientIp": client_ip,
        "Command": "namecheap.domains.dns.setCustom",
        "SLD": sld,
        "TLD": tld,
        "Nameservers": nameservers,
    }

    for attempt in range(retries):
        try:
            resp = requests.get(NAMECHEAP_URL, params=params, timeout=15)
            root = ET.fromstring(resp.text)
            ns = {"nc": "http://api.namecheap.com/xml.response"}
            status = root.attrib.get("Status", "")
            if status == "OK":
                return True, "OK"
            errors = root.findall(".//nc:Error", ns)
            err_msgs = [e.text for e in errors]
            return False, "; ".join(err_msgs) if err_msgs else f"Status: {status}"
        except (ET.ParseError, requests.RequestException) as e:
            if attempt < retries - 1:
                time.sleep(3)
                continue
            return False, f"Error after {retries} retries: {e}"
