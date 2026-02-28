"""Fetches actor context from Notion for the Score Agent."""

import requests
from notion_client import Client
from notion_client.errors import APIResponseError

from config.settings import (
    NOTION_API_KEY,
    NOTION_ACTORS_DB_ID,
    NOTION_EVENTS_DB_ID,
)


def _get_client() -> Client:
    return Client(auth=NOTION_API_KEY)


def fetch_actor_context(actor_page_id: str) -> dict:
    """Fetch actor name, type, linked events, and linked case studies from Notion.

    Returns:
        {
            "name": str,
            "actor_type": str,          # "State" | "Non-State" | "Hybrid" | "IGO" | "Individual"
            "linked_events": [
                {
                    "event_name": str,
                    "date": str,         # ISO date string or "" if missing
                    "pf_signal": str,    # "Widens" | "Narrows" | "No clear effect" | "Indirect"
                    "description": str
                }
            ],
            "linked_case_studies": [
                {
                    "title": str,
                    "summary": str       # empty string if not available
                }
            ]
        }

    Raises RuntimeError on Notion API failure.
    """
    client = _get_client()

    try:
        page = client.pages.retrieve(page_id=actor_page_id)
    except APIResponseError as exc:
        raise RuntimeError(
            f"Notion API error fetching actor page {actor_page_id}: {exc.status} — {exc.body}"
        ) from exc

    props = page.get("properties", {})

    name = _extract_title(props.get("Name", {}))

    actor_type_prop = props.get("Actor Type", {})
    select_obj = actor_type_prop.get("select") or {}
    actor_type = select_obj.get("name", "Non-State")

    linked_events = _fetch_linked_events(client, actor_page_id)
    linked_case_studies = _fetch_linked_case_studies(client, props)

    return {
        "name": name,
        "actor_type": actor_type,
        "linked_events": linked_events,
        "linked_case_studies": linked_case_studies,
    }


def _fetch_linked_events(client: Client, actor_page_id: str) -> list[dict]:
    """Query the Events database for all events linked to this actor via Key Actors."""
    url = f"https://api.notion.com/v1/databases/{NOTION_EVENTS_DB_ID}/query"
    headers = {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28",
    }
    payload = {
        "filter": {
            "property": "Key Actors",
            "relation": {"contains": actor_page_id},
        }
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=15)
        response.raise_for_status()
    except requests.exceptions.RequestException as exc:
        raise RuntimeError(
            f"Notion API error querying events for actor {actor_page_id}: {exc}"
        ) from exc

    events = []
    for event_page in response.json().get("results", []):
        event_props = event_page.get("properties", {})
        events.append({
            "event_name": _extract_title(event_props.get("Event Name", {})),
            "date": _extract_date(event_props.get("Date", {})),
            "pf_signal": _extract_select(event_props.get("PF Signal", {})),
            "description": _extract_rich_text(event_props.get("Description", {})),
        })

    return events


def _fetch_linked_case_studies(client: Client, actor_props: dict) -> list[dict]:
    """Fetch case studies linked from the actor page via a 'Case Studies' relation.

    Returns an empty list if the relation property doesn't exist or is empty.
    """
    case_studies_prop = actor_props.get("Case Studies", {})
    relation_items = case_studies_prop.get("relation", [])
    if not relation_items:
        return []

    case_studies = []
    for item in relation_items:
        page_id = item.get("id", "")
        if not page_id:
            continue
        try:
            page = client.pages.retrieve(page_id=page_id)
            cs_props = page.get("properties", {})
            # Try both "Title" and "Name" as the title property
            title = _extract_title(cs_props.get("Title", {})) or _extract_title(cs_props.get("Name", {}))
            summary = _extract_rich_text(cs_props.get("Summary", {}))
            case_studies.append({"title": title, "summary": summary})
        except APIResponseError:
            continue

    return case_studies


# ── Property extraction helpers ───────────────────────────────────────────────

def _extract_title(prop: dict) -> str:
    items = prop.get("title", [])
    return "".join(item.get("plain_text", "") for item in items)


def _extract_rich_text(prop: dict) -> str:
    items = prop.get("rich_text", [])
    return "".join(item.get("plain_text", "") for item in items)


def _extract_select(prop: dict) -> str:
    select_obj = prop.get("select") or {}
    return select_obj.get("name", "")


def _extract_date(prop: dict) -> str:
    date_obj = prop.get("date") or {}
    return date_obj.get("start", "")
