import streamlit as st
import requests
from typing import Dict, List, Optional, Any


LINEAR_API_URL = "https://api.linear.app/graphql"
LINEAR_API_KEY = st.secrets["LINEAR_API_KEY"]
LINEAR_TEAM_ID = st.secrets.get("LINEAR_TEAM_ID", None)


def gql(query: str, variables: dict = None) -> dict:
    headers = {
        "Authorization": LINEAR_API_KEY,
        "Content-Type": "application/json",
    }
    payload = {"query": query, "variables": variables or {}}

    resp = requests.post(LINEAR_API_URL, json=payload, headers=headers)
    data = resp.json()

    if "errors" in data:
        raise RuntimeError(f"Linear GraphQL Error: {data['errors']}")

    return data["data"]


def get_issue_by_identifier(identifier: str):
    query = """
    query GetIssue($id: String!) {
      issue(id: $id) {
        id
        title
        priority
        updatedAt
        state { id name type }
        team { id name }
      }
    }
    """
    result = gql(query, {"id": identifier})
    return result.get("issue")


def update_linear_ticket_title(issue_id: str, title: str):
    query = """
    mutation UpdateTitle($id: String!, $title: String!) {
      issueUpdate(id: $id, input: { title: $title }) {
        issue { id title }
      }
    }
    """
    result = gql(query, {"id": issue_id, "title": title})
    return result["issueUpdate"]["issue"]


def update_linear_ticket_priority(issue_id: str, priority: int) -> bool:
    query = """
    mutation UpdatePriority($id: String!, $priority: Int!) {
      issueUpdate(id: $id, input: { priority: $priority }) {
        success
      }
    }
    """
    result = gql(query, {"id": issue_id, "priority": priority})
    return result["issueUpdate"]["success"]


def remove_linear_ticket(issue_id: str) -> bool:
    query = """
    mutation DeleteIssue($id: String!) {
      issueDelete(id: $id) { success }
    }
    """
    result = gql(query, {"id": issue_id})
    return result["issueDelete"]["success"]


def fetch_issues(filter_obj: Dict[str, Any]) -> List[Dict]:
    query = """
    query FetchIssues($after: String, $filter: IssueFilter) {
      issues(first: 200, after: $after, filter: $filter) {
        nodes {
          id
          title
          updatedAt
          priority
          state { id name type }
        }
        pageInfo { hasNextPage endCursor }
      }
    }
    """

    all_issues = []
    cursor = None
    while True:
        resp = gql(query, {"after": cursor, "filter": filter_obj})
        issues = resp["issues"]
        all_issues.extend(issues["nodes"])

        if not issues["pageInfo"]["hasNextPage"]:
            break

        cursor = issues["pageInfo"]["endCursor"]

    return all_issues


def get_backlog_linear_tickets():
    return fetch_issues({"state": {"type": {"in": ["unstarted", "backlog"]}}})


def get_in_progress_linear_tickets():
    return fetch_issues({"state": {"type": {"eq": "started"}}})


def get_unstarted_linear_tickets():
    return fetch_issues({"state": {"type": {"in": ["unstarted", "backlog"]}}})


def get_pending_linear_tickets():
    return fetch_issues(
        {"state": {"type": {"in": ["unstarted", "started", "backlog"]}}}
    )


def fetch_linear_labels():
    query = """
    query FetchLabels($after: String) {
      issueLabels(first: 200, after: $after) {
        nodes { id name }
        pageInfo { hasNextPage endCursor }
      }
    }
    """

    labels = []
    cursor = None
    while True:
        data = gql(query, {"after": cursor})
        page = data["issueLabels"]

        labels.extend(page["nodes"])

        if not page["pageInfo"]["hasNextPage"]:
            break

        cursor = page["pageInfo"]["endCursor"]

    return labels


def create_linear_ticket(
    title: str, description: str, label: str = None, priority: int = None
):
    if not LINEAR_TEAM_ID:
        raise RuntimeError("Missing LINEAR_TEAM_ID in st.secrets")

    # Resolve or create label
    label_id = None
    if label:
        labels = fetch_linear_labels()
        match = next((l for l in labels if l["name"] == label), None)
        if match:
            label_id = match["id"]
        else:
            create_label_q = """
            mutation CreateLabel($name: String!, $teamId: String!) {
              issueLabelCreate(input:{name:$name, teamId:$teamId}) {
                issueLabel { id name }
              }
            }
            """
            res = gql(create_label_q, {"name": label, "teamId": LINEAR_TEAM_ID})
            label_id = res["issueLabelCreate"]["issueLabel"]["id"]

    # Create issue
    create_issue_q = """
    mutation CreateIssue($input: IssueCreateInput!) {
      issueCreate(input: $input) {
        issue { id title }
      }
    }
    """

    input_data = {
        "title": title,
        "description": description,
        "teamId": LINEAR_TEAM_ID,
    }
    if priority is not None:
        input_data["priority"] = priority
    if label_id:
        input_data["labelIds"] = [label_id]

    res = gql(create_issue_q, {"input": input_data})
    return res["issueCreate"]["issue"]
