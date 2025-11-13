from typing import List
import logging
import requests
import streamlit as st
from typing import Optional, Dict, Any
from pydantic import ValidationError
from clients.smartlead.schema import (
    SmartleadCampaign,
    SmartleadCampaignLead,
    SmartleadCampaignSequence,
    SmartleadCampaignSequenceInput,
    SmartleadCampaignStatistics,
    SmartleadGetCampaignLeadsResponse,
)


SMARTLEAD_API = "https://server.smartlead.ai/api/v1/"


def query_smartlead(
    endpoint: str,
    method: str,
    headers: Optional[Dict[str, str]] = None,
    body: Optional[Any] = None,
    query_params: Optional[Dict[str, Any]] = None,
) -> Any:
    url = f"{SMARTLEAD_API}{endpoint}"
    params = query_params or {}
    params["api_key"] = st.secrets["SMARTLEAD_API_KEY"]

    try:
        response = requests.request(
            method=method.upper(),
            url=url,
            headers=headers,
            json=body,
            params=params,
            timeout=30,
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as e:
        try:
            error_data = response.json()
            error_msg = error_data.get("error", str(e))
            detailed_msg = error_data.get("message", "")
        except ValueError:
            error_msg = str(e)
            detailed_msg = ""
        raise Exception(
            f"Email Server Error with {endpoint} - {error_msg} : {detailed_msg}"
        ) from e
    except requests.exceptions.RequestException as e:
        raise Exception(f"Email Server Error with {endpoint} - {str(e)}") from e


def get_campaign_top_level_analytics_for_date_range(
    campaign_id: str, start_date: str, end_date: str
) -> Any:
    """Get campaign top-level analytics for a specific date range."""
    response = query_smartlead(
        endpoint=f"campaigns/{campaign_id}/top-level-analytics-by-date",
        method="GET",
        query_params={"start_date": start_date, "end_date": end_date},
    )
    return response


def get_campaign_by_id(campaign_id: int) -> SmartleadCampaign:
    result: Any = query_smartlead(endpoint=f"campaigns/{campaign_id}", method="GET")

    try:
        campaign = SmartleadCampaign.model_validate(result)
        return campaign
    except ValidationError as e:
        raise ValueError(
            f"Invalid campaign data from Smartlead API for ID {campaign_id}: {e}"
        ) from e


def get_leads_by_campaign_id_with_pagination(
    campaign_id: int,
    lead_category_id: Optional[int] = None,
    event_time: Optional[str] = None,
) -> List[SmartleadCampaignLead]:
    leads: List[SmartleadCampaignLead] = []

    # Initial request
    params = {}
    if event_time:
        params["event_time_gt"] = event_time
    if lead_category_id:
        params["lead_category_id"] = lead_category_id

    try:
        response = query_smartlead(
            endpoint=f"campaigns/{campaign_id}/leads",
            method="GET",
            query_params=params,
        )
        first_page = SmartleadGetCampaignLeadsResponse.model_validate(response)
        total_leads = first_page.total_leads
        leads.extend(first_page.data)
    except Exception as e:
        logging.error(f"Error fetching first page: {e}")
        return leads

    # Pagination
    while len(leads) < total_leads:
        page = []
        try:
            offset_params = {"offset": len(leads)}
            if event_time:
                offset_params["event_time_gt"] = event_time

            response = query_smartlead(
                endpoint=f"campaigns/{campaign_id}/leads",
                method="GET",
                query_params=offset_params,
            )

            page = SmartleadGetCampaignLeadsResponse.model_validate(response)

            leads.extend(page.data)
        except Exception as e:
            logging.error(
                f"Error getting leads for campaign {campaign_id} at offset {len(leads)}: {e}"
            )
            continue

    return leads


def get_campaigns() -> list[SmartleadCampaign]:
    result = query_smartlead("/campaigns", method="GET")

    if not isinstance(result, list):
        raise RuntimeError(
            f"Unexpected Smartlead response (expected list, got {type(result)}): {result}"
        )

    try:
        # 🚀 Pydantic v2: validate a list of campaign objects
        return [SmartleadCampaign.model_validate(item) for item in result]

    except ValidationError as e:
        raise RuntimeError(f"Smartlead campaign schema validation failed:\n{e}") from e


def get_campaign_statistics(campaign_id: str) -> SmartleadCampaignStatistics:
    try:
        resp = query_smartlead(f"/campaigns/{campaign_id}/analytics", method="GET")
    except Exception as e:
        raise RuntimeError(
            f"Failed to get campaign statistics for campaign {campaign_id}: {e}"
        ) from e

    try:
        return SmartleadCampaignStatistics.model_validate(resp, strict=False)
    except ValidationError as e:
        raise RuntimeError(
            f"Smartlead campaign statistics schema validation failed for {campaign_id}:\n{e}"
        ) from e


def get_campaign_sequences(campaign_id: int) -> List[SmartleadCampaignSequence]:
    result = query_smartlead(
        endpoint=f"/campaigns/{campaign_id}/sequences",
        method="GET",
    )

    if not isinstance(result, list):
        raise RuntimeError(
            f"Unexpected Smartlead response for sequences (expected list, got {type(result)}): {result}"
        )

    try:
        return [SmartleadCampaignSequence.model_validate(item) for item in result]
    except ValidationError as e:
        raise RuntimeError(
            f"Smartlead campaign sequences schema validation failed for campaign {campaign_id}:\n{e}"
        ) from e


def add_sequences_to_campaign(
    *, campaign_id: int, input_sequences: List[SmartleadCampaignSequenceInput]
) -> None:
    try:
        sequences_payload = [
            seq.model_dump(by_alias=True, exclude_none=True) for seq in input_sequences
        ]
    except ValidationError as e:
        raise RuntimeError(f"Sequence input validation failed: {e}") from e

    try:
        query_smartlead(
            endpoint=f"/campaigns/{int(campaign_id)}/sequences",
            method="POST",
            body={"sequences": sequences_payload},
        )
    except Exception as e:
        # Match TS error semantics
        msg = getattr(e, "message", str(e))
        raise RuntimeError(
            f"Error adding sequences to campaign {campaign_id}: {msg}"
        ) from e
