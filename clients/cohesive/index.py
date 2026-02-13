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
