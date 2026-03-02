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
    """Fetch actor name, type, linked events, case studies, and relationship context from Notion.

    Returns:
        {
            "name": str,
            "actor_type": str,
            "proxy_depth": str,           # "Patron" | "Principal" | "Agent" | "Autonomous" | "None"
            "linked_events": [...],
            "linked_case_studies": [...],
            "patron_context": {           # None if no patron relation set
                "name": str,
                "authority_score": float | None,
                "reach_score": float | None,
                "pf_score": float | None,
                "status": str,
                "score_reasoning": str,
            } | None,
            "proxy_actors": [             # actors that list this actor as their patron
                {
                    "name": str,
                    "authority_score": float | None,
                    "reach_score": float | None,
                    "pf_score": float | None,
                    "proxy_depth": str,
                    "status": str,
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
    actor_type = (actor_type_prop.get("select") or {}).get("name", "Non-State")

    proxy_depth_prop = props.get("Proxy Depth", {})
    proxy_depth = (proxy_depth_prop.get("select") or {}).get("name", "None")

    linked_events = _fetch_linked_events(client, actor_page_id)
    linked_case_studies = _fetch_linked_case_studies(client, props)
    patron_context = _fetch_patron_context(client, props)
    proxy_actors = _fetch_proxy_actors(actor_page_id)

    return {
        "name": name,
        "actor_type": actor_type,
        "proxy_depth": proxy_depth,
        "linked_events": linked_events,
        "linked_case_studies": linked_case_studies,
        "patron_context": patron_context,
        "proxy_actors": proxy_actors,
    }


def _fetch_patron_context(client: Client, actor_props: dict) -> dict | None:
    """Fetch the patron state's current scores and status via the Patron State relation.

    Returns a dict with the patron's name, scores, and reasoning, or None if no patron is set.
    """
    patron_prop = actor_props.get("Patron State", {})
    relation_items = patron_prop.get("relation", [])
    if not relation_items:
        return None

    patron_page_id = relation_items[0].get("id", "")
    if not patron_page_id:
        return None

    try:
        page = client.pages.retrieve(page_id=patron_page_id)
    except APIResponseError:
        return None

    props = page.get("properties", {})
    name = _extract_title(props.get("Name", {}))
    authority = props.get("Authority Score", {}).get("number")
    reach = props.get("Reach Score", {}).get("number")
    pf_score = (authority * 0.6 + reach * 0.4) if (authority is not None and reach is not None) else None
    status = (props.get("Status", {}).get("select") or {}).get("name", "")
    reasoning = _extract_text(props.get("Score Reasoning", {}))

    return {
        "name": name,
        "authority_score": authority,
        "reach_score": reach,
        "pf_score": pf_score,
        "status": status,
        "score_reasoning": reasoning,
    }


def _fetch_proxy_actors(actor_page_id: str) -> list[dict]:
    """Find all actors in the registry that list this actor as their Patron State.

    This surfaces the actors this entity sponsors, so the score agent can reason
    about the burden and reach amplification of managing a proxy network.
    """
    url = f"https://api.notion.com/v1/databases/{NOTION_ACTORS_DB_ID}/query"
    headers = {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28",
    }
    payload = {
        "filter": {
            "property": "Patron State",
            "relation": {"contains": actor_page_id},
        }
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=15)
        response.raise_for_status()
    except requests.exceptions.RequestException:
        return []

    proxies = []
    for page in response.json().get("results", []):
        props = page.get("properties", {})
        name = _extract_title(props.get("Name", {}))
        authority = props.get("Authority Score", {}).get("number")
        reach = props.get("Reach Score", {}).get("number")
        pf_score = (authority * 0.6 + reach * 0.4) if (authority is not None and reach is not None) else None
        proxy_depth = (props.get("Proxy Depth", {}).get("select") or {}).get("name", "")
        status = (props.get("Status", {}).get("select") or {}).get("name", "")
        proxies.append({
            "name": name,
            "authority_score": authority,
            "reach_score": reach,
            "pf_score": pf_score,
            "proxy_depth": proxy_depth,
            "status": status,
        })

    return proxies


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
    """Fetch case studies linked from the actor page via a 'Case Studies' relation."""
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


def _extract_text(prop: dict) -> str:
    """Extract from either rich_text or plain text property."""
    if "rich_text" in prop:
        return _extract_rich_text(prop)
    return prop.get("text", {}).get("content", "") if isinstance(prop.get("text"), dict) else ""


def _extract_select(prop: dict) -> str:
    select_obj = prop.get("select") or {}
    return select_obj.get("name", "")


def _extract_date(prop: dict) -> str:
    date_obj = prop.get("date") or {}
    return date_obj.get("start", "")


def fetch_peer_actors(actor_page_id: str, actor_type: str, limit: int = 5) -> list[dict]:
    """Fetch scored peer actors of the same type for calibration context.

    Returns up to `limit` actors with non-null scores, excluding the actor being scored.
    Used to give the score agent a local calibration frame alongside global anchors.
    """
    from config.settings import NOTION_ACTORS_DB_ID, NOTION_API_KEY

    url = f"https://api.notion.com/v1/databases/{NOTION_ACTORS_DB_ID}/query"
    headers = {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28",
    }
    payload = {
        "filter": {
            "and": [
                {
                    "property": "Actor Type",
                    "select": {"equals": actor_type},
                },
                {
                    "property": "Authority Score",
                    "number": {"is_not_empty": True},
                },
                {
                    "property": "Reach Score",
                    "number": {"is_not_empty": True},
                },
            ]
        },
        "page_size": 20,
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=15)
        response.raise_for_status()
    except requests.exceptions.RequestException:
        return []

    peers = []
    for page in response.json().get("results", []):
        if page["id"] == actor_page_id:
            continue
        props = page.get("properties", {})
        name_prop = props.get("Name", {})
        name = "".join(item.get("plain_text", "") for item in name_prop.get("title", []))
        if not name:
            continue
        authority = props.get("Authority Score", {}).get("number")
        reach = props.get("Reach Score", {}).get("number")
        if authority is None or reach is None:
            continue
        pf = round(authority * 0.6 + reach * 0.4, 1)
        reasoning_prop = props.get("Score Reasoning", {})
        reasoning = "".join(
            item.get("plain_text", "") for item in reasoning_prop.get("rich_text", [])
        )
        peers.append({
            "name": name,
            "authority": int(authority),
            "reach": int(reach),
            "pf_score": pf,
            "reasoning_snippet": reasoning[:200] if reasoning else "",
        })
        if len(peers) >= limit:
            break

    return peers
