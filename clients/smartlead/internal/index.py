import os
from typing import Any, Dict, List, Optional
import requests

from ..schema import (
    SmartleadCampaignLeadMapping,
    SmartleadGetCampaignSequencesViaGraphQLResponse,
)


def get_campaign_sequences(
    campaign_id: int,
) -> Any:
    query = """
    query getSequencesByCampaignId($id: Int!) {
      email_campaigns_by_pk(id: $id) {
        name
        sequences: email_campaign_seq_mappings(order_by: {seq_number: asc}) {
          id
          ...BasicEmailCampaignSeqMappingsFragment
          email_seq_variant_mappings {
            id
            variant_label
            __typename
          }
          __typename
        }
        __typename
      }
    }

    fragment BasicEmailCampaignSeqMappingsFragment on email_campaign_seq_mappings {
      seq_number
      subject
      email_body
      seq_type
      seq_schedule_type
      __typename
    }
    """

    result = query_smartlead_internal_graphql_endpoint(
        method="POST",
        body={
            "query": query,
            "variables": {"id": campaign_id},
            "operationName": "getSequencesByCampaignId",
        },
    )

    return SmartleadGetCampaignSequencesViaGraphQLResponse.model_validate(result)


def remove_multiple_leads_from_campaign(
    smartlead_campaign_id: str, email_lead_ids: list[int], email_lead_map_ids: list[int]
) -> dict:
    if len(email_lead_ids) != len(email_lead_map_ids):
        raise ValueError("emailLeadIds and emailLeadMapIds must have the same length")

    body = {
        "campaignId": smartlead_campaign_id,
        "emailLeadIds": email_lead_ids,
        "emailLeadMapIds": email_lead_map_ids,
    }

    return query_smartlead_internal_rest_endpoint(
        endpoint="email-campaigns/delete-email-campaign-multiple-leads",
        method="POST",
        body=body,
    )


def update_smartlead_campaign_follow_up_percentage(
    *,
    campaign_id: int,
    follow_up_percentage: float,
) -> Dict[str, Any]:
    variables = {
        "id": campaign_id,
        "changes": {"follow_up_percentage": follow_up_percentage},
    }

    query = """
    mutation updateCampaignById($id: Int!, $changes: email_campaigns_set_input!) {
      update_email_campaigns_by_pk(pk_columns: {id: $id}, _set: $changes) {
        id
        __typename
      }
    }
    """

    return query_smartlead_internal_graphql_endpoint(
        method="POST",
        body={
            "query": query,
            "variables": variables,
            "operationName": "updateCampaignById",
        },
    )


def get_campaign_analytics_by_id(
    *,
    campaign_id: int,
    start_date: str,
    end_date: str,
    timezone: str = "America/New_York",
) -> list[Dict[str, Any]]:
    """
    Get campaign analytics for a specific date range using GraphQL.

    Args:
        campaign_id: The Smartlead campaign ID
        start_date: Start date in format "YYYY/MM/DD"
        end_date: End date in format "YYYY/MM/DD"
        timezone: Timezone string (default: "America/New_York")

    Returns:
        List of daily analytics with sent_count, bounce_count, open_count,
        click_count, reply_count, skipped_count
    """
    query = """
    query getCampaignAnalyticsById($args: grouped_email_analytics_timezone_args!) {
      grouped_email_analytics_timezone(args: $args) {
        date
        sent_count
        bounce_count
        open_count
        click_count
        reply_count
        skipped_count
        __typename
      }
    }
    """

    variables = {
        "args": {
            "campaign_id": campaign_id,
            "start_date": start_date,
            "end_date": end_date,
            "timezone": timezone,
        }
    }

    result = query_smartlead_internal_graphql_endpoint(
        method="POST",
        body={
            "operationName": "getCampaignAnalyticsById",
            "variables": variables,
            "query": query,
        },
    )

    # Extract the analytics data from the response
    if "data" in result and "grouped_email_analytics_timezone" in result["data"]:
        return result["data"]["grouped_email_analytics_timezone"]

    return []


def get_campaign_leads_by_id_with_mapping(
    campaign_id: int, lead_category: Optional[int] = None
) -> List[SmartleadCampaignLeadMapping]:
    variables = {
        "offset": 0,
        "limit": 10000,
        "where": {
            "email_campaign_id": {"_eq": campaign_id},
            "user_id": {"_eq": 21050},
        },
        "campaignId": campaign_id,
    }
    if lead_category is not None:
        variables["where"]["lead_category_id"] = {"_eq": lead_category}

    query = """
    query getCampaignLeadsByIdWithMapping($offset: Int!, $limit: Int!, $where: email_campaign_leads_mappings_bool_exp!, $campaignId: Int!) {
      email_campaign_leads_mappings(
        where: $where
        offset: $offset
        limit: $limit
        order_by: {created_at: asc, id: asc}
      ) {
        id
        status
        current_seq_num
        email_campaign_seq_id
        last_sent_time
        next_timestamp_to_reach
        email_lead {
          ...EmailLeadsFragment
        }
        linkedin_cookie {
          token_name
        }
        email_account {
          username
          mappingExists: email_campaign_account_mappings(
            where: {email_campaign_id: {_eq: $campaignId}}
            limit: 1
          ) {
            id
          }
        }
      }
    }

    fragment EmailLeadsFragment on email_leads {
      id
      email
      last_name
      first_name
      phone_number
      company_name
      website
      company_url
      location
      custom_fields
      linkedin_profile
      esp_domain_type
      seg_type
    }
    """
    response = query_smartlead_internal_graphql_endpoint(
        method="POST",
        body={
            "query": query,
            "variables": variables,
            "operationName": "getCampaignLeadsByIdWithMapping",
        },
    )
    mappings = response["data"]["email_campaign_leads_mappings"]
    result = []
    for m in mappings:
        try:
            result.append(SmartleadCampaignLeadMapping.model_validate(m))
        except Exception as e:
            print(f"Validation failed for mapping: {m}")
            print(f"Error: {e}")
    return result


def query_smartlead_internal_rest_endpoint(
    endpoint: str,
    method: str,
    body: dict = None,
    headers: dict = None,
    query_params: dict = None,
) -> dict:
    import requests
    import os

    base_url = "https://server.smartlead.ai/api/"
    url = f"{base_url}{endpoint}"

    auth_token = os.environ.get("SMARTLEAD_INTERNAL_API_TOKEN")
    if not auth_token:
        raise RuntimeError("Missing SMARTLEAD_INTERNAL_API_TOKEN")

    final_headers = {
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json",
    }
    if headers:
        final_headers.update(headers)

    try:
        response = requests.request(
            method=method.upper(),
            url=url,
            headers=final_headers,
            json=body,
            params=query_params,
            timeout=120,
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        try:
            err_json = response.json()
            err_msg = err_json.get("error", str(e))
            detail = err_json.get("message", "")
        except Exception:
            err_msg = str(e)
            detail = ""
        raise RuntimeError(f"Email Server Error with {endpoint} - {err_msg} : {detail}")


class SmartleadGraphQLError(RuntimeError):
    pass


def query_smartlead_internal_graphql_endpoint(
    *,
    method: str,
    headers: Optional[Dict[str, str]] = None,
    body: Optional[Any] = None,
    query_params: Optional[Dict[str, Any]] = None,
    timeout: int = 120,
) -> Dict[str, Any]:
    INTERNAL_SMARTLEAD_GRAPHQL_API = "https://fe-gql.smartlead.ai/v1/graphql"
    token = os.getenv("SMARTLEAD_INTERNAL_API_TOKEN")
    if not token:
        raise SmartleadGraphQLError("Missing SMARTLEAD_INTERNAL_API_TOKEN env var")

    base_headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    merged_headers = {**base_headers, **(headers or {})}

    # Try to extract operationName for debug logs (mirrors the TS behavior)
    op_name = None
    if isinstance(body, dict):
        op_name = body.get("operationName")

    try:
        resp = requests.request(
            method=method.upper(),
            url=INTERNAL_SMARTLEAD_GRAPHQL_API,
            headers=merged_headers,
            json=body,
            params=query_params,
            timeout=timeout,
        )
        # Raise for HTTP errors (>=400)
        resp.raise_for_status()
        return resp.json()

    except requests.HTTPError as e:
        # HTTP error with a response payload
        err_data = None
        try:
            err_data = resp.json()  # type: ignore[has-type]
        except Exception:
            pass

        # Mimic the TS logic: if JSON has 'error' (and maybe 'message'), surface it
        if isinstance(err_data, dict) and "error" in err_data:
            msg = f"Email Server Error with GraphQL - {err_data.get('error')}"
            if "message" in err_data:
                msg += f" : {err_data.get('message')}"
        else:
            # Fallback to text or the exception message
            msg = f"Email Server Error with GraphQL - {getattr(err_data, 'error', None) or resp.text or str(e)}"
        raise SmartleadGraphQLError(msg) from e

    except requests.RequestException as e:
        # Network/timeout/connection issues
        # Try to pull nested response error message if present
        msg = f"Email Server Error with GraphQL - {getattr(getattr(e, 'response', None), 'text', None) or str(e)}"
        raise SmartleadGraphQLError(msg) from e
