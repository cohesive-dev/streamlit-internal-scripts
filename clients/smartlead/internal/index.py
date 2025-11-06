import os
from typing import Any, Dict, Optional
import requests


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
            timeout=30,
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
    timeout: int = 30,
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
