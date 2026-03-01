"""Notion data fetcher for the PowerFlow briefing agent.

Queries four Notion databases for recent activity and returns a unified
dict ready for synthesis. Uses raw requests.post (not notion-client) to
match the ingestion agent's pattern.
"""

from __future__ import annotations

import datetime
from typing import Any

import requests

from config.settings import NOTION_API_KEY

_NOTION_VERSION = "2022-06-28"
_NOTION_BASE = "https://api.notion.com/v1"

# Database IDs
_EVENTS_DB_ID = "70e9768bfcec49a9aa8565d5aa1f1881"
_INTEL_FEEDS_DB_ID = "3835cb822ae441a5a18cb4271d9fe955"
_SCORE_SNAPSHOTS_DB_ID = "e96696510cac4435a52e89be9fb6a969"
_SCENARIOS_DB_ID = "430eb13962d44154b9761785faf01300"


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Content-Type": "application/json",
        "Notion-Version": _NOTION_VERSION,
    }


def _query_database(db_id: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Execute a Notion database query with auto-pagination. Returns all results."""
    url = f"{_NOTION_BASE}/databases/{db_id}/query"
    results: list[dict[str, Any]] = []
    start_cursor: str | None = None

    while True:
        body = {**payload}
        if start_cursor:
            body["start_cursor"] = start_cursor

        response = requests.post(url, headers=_headers(), json=body, timeout=20)
        response.raise_for_status()
        data = response.json()

        results.extend(data.get("results", []))

        if data.get("has_more") and data.get("next_cursor"):
            start_cursor = data["next_cursor"]
        else:
            break

    return results


def _plain_text(prop: dict[str, Any] | None) -> str:
    """Extract plain text from a Notion title or rich_text property."""
    if prop is None:
        return ""
    items = prop.get("title") or prop.get("rich_text") or []
    return "".join(item.get("plain_text", "") for item in items)


def _select_value(prop: dict[str, Any] | None) -> str:
    """Extract the name from a Notion select property."""
    if prop is None:
        return ""
    sel = prop.get("select")
    return sel.get("name", "") if sel else ""


def _number_value(prop: dict[str, Any] | None) -> float | None:
    """Extract a number from a Notion number property."""
    if prop is None:
        return None
    return prop.get("number")


def _date_value(prop: dict[str, Any] | None) -> str:
    """Extract the start date string from a Notion date property."""
    if prop is None:
        return ""
    d = prop.get("date")
    return d.get("start", "") if d else ""


def _relation_names(prop: dict[str, Any] | None) -> list[str]:
    """Extract relation IDs from a Notion relation property (names require extra calls)."""
    if prop is None:
        return []
    return [r.get("id", "") for r in prop.get("relation", [])]


def _relation_title(page_id: str) -> str:
    """Fetch a page's title by ID. Returns empty string on failure."""
    try:
        url = f"{_NOTION_BASE}/pages/{page_id}"
        response = requests.get(url, headers=_headers(), timeout=10)
        response.raise_for_status()
        data = response.json()
        props = data.get("properties", {})
        for key in ("Name", "Title", "Actor"):
            if key in props:
                return _plain_text(props[key])
        # Fallback: return the first title-type property found
        for prop in props.values():
            if prop.get("type") == "title":
                return _plain_text(prop)
    except Exception:
        pass
    return ""


def _iso_cutoff(lookback_days: int) -> str:
    """Return an ISO 8601 datetime string for N days ago (UTC)."""
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=lookback_days)
    return cutoff.isoformat(timespec="seconds")


def _date_range_label(lookback_days: int) -> str:
    """Return a human-readable date range label e.g. 'Feb 22 – Feb 28, 2026'."""
    today = datetime.datetime.utcnow()
    cutoff = today - datetime.timedelta(days=lookback_days)
    # Windows strftime does not support %-d; use %#d on Windows
    try:
        return f"{cutoff.strftime('%b %-d')} – {today.strftime('%b %-d, %Y')}"
    except ValueError:
        return f"{cutoff.strftime('%b %#d')} – {today.strftime('%b %#d, %Y')}"


def fetch_events(lookback_days: int = 7) -> list[dict[str, Any]]:
    """Fetch recent Events Timeline entries."""
    cutoff = _iso_cutoff(lookback_days)
    payload = {
        "filter": {
            "timestamp": "created_time",
            "created_time": {"on_or_after": cutoff},
        },
        "sorts": [{"timestamp": "created_time", "direction": "descending"}],
    }

    try:
        pages = _query_database(_EVENTS_DB_ID, payload)
    except Exception:
        return []

    results: list[dict[str, Any]] = []
    for page in pages:
        props = page.get("properties", {})
        results.append({
            "name": _plain_text(props.get("Name") or props.get("Event Name")),
            "event_type": _select_value(props.get("Event Type")),
            "description": _plain_text(props.get("Description")),
            "pf_signal": _select_value(props.get("PF Signal")),
            "date": _date_value(props.get("Date") or props.get("date")),
        })
    return results


def fetch_intel_feeds(lookback_days: int = 7) -> list[dict[str, Any]]:
    """Fetch recent Intelligence Feeds entries."""
    cutoff = _iso_cutoff(lookback_days)
    payload = {
        "filter": {
            "timestamp": "created_time",
            "created_time": {"on_or_after": cutoff},
        },
        "sorts": [{"timestamp": "created_time", "direction": "descending"}],
    }

    try:
        pages = _query_database(_INTEL_FEEDS_DB_ID, payload)
    except Exception:
        return []

    results: list[dict[str, Any]] = []
    for page in pages:
        props = page.get("properties", {})
        results.append({
            "name": _plain_text(props.get("Title") or props.get("Name")),
            "so_what_summary": _plain_text(props.get("So What Summary")),
            "confidence_shift": _select_value(props.get("Confidence Shift")),
            "gap_implication": _select_value(props.get("Gap Implication") or props.get("PF Signal")),
        })
    return results


def fetch_score_snapshots(lookback_days: int = 7) -> list[dict[str, Any]]:
    """Fetch Score Snapshots where Score Delta != 0 and Snapshot Date is recent."""
    cutoff_date = (
        datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=lookback_days)
    ).date().isoformat()

    payload = {
        "filter": {
            "and": [
                {
                    "property": "Snapshot Date",
                    "date": {"on_or_after": cutoff_date},
                },
                {
                    "property": "Score Delta",
                    "number": {"is_not_empty": True},
                },
            ]
        },
        "sorts": [{"property": "Score Delta", "direction": "ascending"}],
    }

    try:
        pages = _query_database(_SCORE_SNAPSHOTS_DB_ID, payload)
    except Exception:
        return []

    results: list[dict[str, Any]] = []
    for page in pages:
        props = page.get("properties", {})

        # Use the snapshot Title as the actor label — relation objects in query
        # responses only contain IDs, so per-page fetches are not worth the cost.
        title = _plain_text(props.get("Title") or props.get("Name"))

        results.append({
            "title": title,
            "score": _number_value(props.get("Score")),
            "score_delta": _number_value(props.get("Score Delta")),
            "trigger_notes": _plain_text(props.get("Trigger Notes")),
            "actor": title,
        })
    return results


def fetch_active_scenarios() -> list[dict[str, Any]]:
    """Fetch all Scenarios & Stress Tests with Status = 'Active'."""
    payload = {
        "filter": {
            "property": "Status",
            "select": {"equals": "Active"},
        },
        "sorts": [{"property": "Probability Estimate", "direction": "descending"}],
    }

    try:
        pages = _query_database(_SCENARIOS_DB_ID, payload)
    except Exception:
        return []

    results: list[dict[str, Any]] = []
    for page in pages:
        props = page.get("properties", {})
        # Notion title property key is "Scenario Name", not "Name"
        name_prop = props.get("Scenario Name", {})
        title_items = name_prop.get("title", [])
        name = title_items[0]["plain_text"] if title_items else ""
        results.append({
            "name": name,
            "scenario_class": _select_value(props.get("Scenario Class")),
            "probability_estimate": _select_value(props.get("Probability Estimate")),
            "trigger_condition": _plain_text(props.get("Trigger Condition")),
        })
    return results


def fetch_all(lookback_days: int = 7) -> dict[str, Any]:
    """Fetch all data sources and return a unified brief payload.

    Args:
        lookback_days: How many days back to query. Default 7 for weekly brief.
                       Pass 30 for a monthly brief.

    Returns:
        Dict with keys: events, intel_feeds, score_snapshots, active_scenarios, date_range.
        Any database returning zero results is included as an empty list rather than raising.
    """
    events = fetch_events(lookback_days)
    intel_feeds = fetch_intel_feeds(lookback_days)
    score_snapshots = fetch_score_snapshots(lookback_days)
    active_scenarios = fetch_active_scenarios()

    return {
        "events": events,
        "intel_feeds": intel_feeds,
        "score_snapshots": score_snapshots,
        "active_scenarios": active_scenarios,
        "date_range": _date_range_label(lookback_days),
    }
