import os
from typing import List, Any, Optional, Dict
import requests

from ..smartlead.internal.index import query_smartlead_internal_graphql_endpoint

BASE_LEAD_GENERATION_SERVICE_URL = (
    "https://cohesive-lead-generation-hkdjgqbthtgfe6ah.eastus-01.azurewebsites.net/"
)
COHESIVE_PLATFORM_URL = "https://extension.cohesiveapp.com/api/"


def query_cohesive(
    *,
    method: str,
    url: Optional[str] = None,
    endpoint: Optional[str] = None,
    headers: Optional[Dict[str, Any]] = None,
    body: Optional[Dict[str, Any]] = None,
    query_params: Optional[Dict[str, Any]] = None,
    timeout: int = 30,
) -> Any:
    """
    Python equivalent of queryCohesive (axios wrapper)
    """
    final_url = url or f"{COHESIVE_PLATFORM_URL}{endpoint}"

    response = requests.request(
        method=method,
        url=final_url,
        headers=headers,
        json=body,  # axios `data` → requests `json`
        params=query_params,  # axios `params`
        timeout=timeout,
    )

    response.raise_for_status()
    return response.json()


def auto_schedule_restart_lead_generation_jobs(
    lead_generation_job_ids: List[str],
) -> Any:
    """
    Python equivalent of autoScheduleRestartLeadGenerationJobs
    """
    url = f"{BASE_LEAD_GENERATION_SERVICE_URL}auto-schedule-restart"

    # Increase timeout to 120 seconds to avoid timeout errors
    return query_cohesive(
        method="POST",
        url=url,
        body={"leadGenerationJobIds": lead_generation_job_ids},
        query_params=None,
        headers=None,
        timeout=120,
    )


def get_campaign_leads_by_id_with_mapping(
    *,
    campaign_id: int,
    lead_category: Optional[int] = None,
) -> List[Dict[str, Any]]:
    where_clause = {
        "email_campaign_id": {"_eq": campaign_id},
        "user_id": {"_eq": 21050},
    }

    if lead_category is not None:
        where_clause["lead_category_id"] = {"_eq": lead_category}

    variables = {
        "offset": 0,
        "limit": 10000,
        "where": where_clause,
        "campaignId": campaign_id,
    }

    query = """
    query getCampaignLeadsByIdWithMapping(
      $offset: Int!,
      $limit: Int!,
      $where: email_campaign_leads_mappings_bool_exp!,
      $campaignId: Int!
    ) {
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
            "operation_name": "getCampaignLeadsByIdWithMapping",
        },
    )

    # Optional schema parsing / validation hook
    if "errors" in response:
        raise RuntimeError(response["errors"])

    return response["data"]["email_campaign_leads_mappings"]
