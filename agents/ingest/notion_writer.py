"""Notion API writes for Sources, Events, Intelligence Feeds, and Actors Registry databases."""

import datetime
from typing import Any

from notion_client import Client
from notion_client.errors import APIResponseError
from rich.console import Console

from config.settings import (
    ACTOR_TYPE_NOTION_MAP,
    NOTION_ACTIVITY_LOG_DB_ID,
    NOTION_ACTORS_DB_ID,
    NOTION_API_KEY,
    NOTION_EVENTS_DB_ID,
    NOTION_INTEL_FEEDS_DB_ID,
    NOTION_SOURCES_DB_ID,
)

console = Console()


def write_source(source: dict[str, Any]) -> tuple[str, str]:
    """Create a Source record in Notion.

    Returns (page_id, page_url).
    Raises RuntimeError on API failure.
    """
    client = _get_client()

    properties = {
        "Title": _title(source.get("title", "Untitled")),
        "Source Type": _select(source.get("source_type", "Other")),
        "Reliability": _select(source.get("reliability", "Medium")),
        "Author / Organization": _rich_text(source.get("author_organization", "")),
        "Summary": _rich_text(source.get("summary", "")),
    }

    if url := source.get("url"):
        properties["URL"] = {"url": url}

    if pub_date := source.get("publication_date"):
        properties["Publication Date"] = _date(pub_date)

    try:
        response = client.pages.create(
            parent={"database_id": NOTION_SOURCES_DB_ID},
            properties=properties,
        )
    except APIResponseError as exc:
        raise RuntimeError(
            f"Notion API error writing Source record: {exc.status} — {exc.body}"
        ) from exc

    page_id = response["id"]
    page_url = response.get("url", f"https://notion.so/{page_id.replace('-', '')}")
    return page_id, page_url


def write_event(event: dict[str, Any], source_page_id: str) -> tuple[str, str]:
    """Create an Event record in Notion, linked to the given Source page.

    Returns (page_id, page_url).
    Raises RuntimeError on API failure.
    """
    client = _get_client()

    properties = {
        "Event Name": _title(event.get("event_name", "Untitled Event")),
        "Event Type": _select(event.get("event_type", "Other")),
        "Description": _rich_text(event.get("description", "")),
        "Impact on Sovereignty Gap": _select(
            event.get("impact_on_sovereignty_gap", "Indirect")
        ),
        "Key Sources": {
            "relation": [{"id": source_page_id}]
        },
    }

    if event_date := event.get("date"):
        properties["Date"] = _date(event_date)

    try:
        response = client.pages.create(
            parent={"database_id": NOTION_EVENTS_DB_ID},
            properties=properties,
        )
    except APIResponseError as exc:
        raise RuntimeError(
            f"Notion API error writing Event record: {exc.status} — {exc.body}"
        ) from exc

    page_id = response["id"]
    page_url = response.get("url", f"https://notion.so/{page_id.replace('-', '')}")
    return page_id, page_url


_GAP_IMPLICATION_MAP: dict[str, str] = {
    "Widens": "Widening",
    "Narrows": "Narrowing",
    "No clear effect": "Stable",
    "Indirect": "Unclear",
}

_SOURCE_TYPE_MAP: dict[str, str] = {
    "Think tank": "Think Tank",
}


def write_intel_feed(
    source: dict[str, Any],
    event: dict[str, Any],
    screen_result: dict[str, Any],
) -> tuple[str, str]:
    """Create an Intelligence Feed record in Notion.

    Returns (page_id, page_url).
    Raises RuntimeError on API failure.
    """
    client = _get_client()

    raw_source_type = source.get("source_type", "Other")
    source_type = _SOURCE_TYPE_MAP.get(raw_source_type, raw_source_type)

    raw_gap = event.get("impact_on_sovereignty_gap", "Indirect")
    gap_implication = _GAP_IMPLICATION_MAP.get(raw_gap, "Unclear")

    score: int = screen_result.get("score", 0)
    if score >= 80:
        confidence_shift = "Major Update"
    elif score >= 60:
        confidence_shift = "Minor Update"
    elif score >= 40:
        confidence_shift = "Confirms Existing"
    else:
        confidence_shift = "New Thread"

    properties: dict[str, Any] = {
        "Title": _title(source.get("title", "Untitled")),
        "Source Type": _select(source_type),
        "Reliability": _select(source.get("reliability", "Medium")),
        "Author": _rich_text(source.get("author_organization", "")),
        "Gap Implication": _select(gap_implication),
        "So What Summary": _rich_text(screen_result.get("reasoning", "")),
        "Confidence Shift": _select(confidence_shift),
        "Ingestion Status": _select("Integrated"),
        "Agent Processed": {"checkbox": True},
    }

    if pub_date := source.get("publication_date"):
        properties["Publication Date"] = _date(pub_date)

    try:
        response = client.pages.create(
            parent={"database_id": NOTION_INTEL_FEEDS_DB_ID},
            properties=properties,
        )
    except APIResponseError as exc:
        raise RuntimeError(
            f"Notion API error writing Intelligence Feed record: {exc.status} — {exc.body}"
        ) from exc

    page_id = response["id"]
    page_url = response.get("url", f"https://notion.so/{page_id.replace('-', '')}")
    return page_id, page_url


def write_actors(
    actors: list[dict[str, Any]], event_page_id: str
) -> list[tuple[str, str, str, bool]]:
    """Create or find Actor records in the Actors Registry, then link them to the Event page.

    For each actor, checks if a page with the same name already exists in the Actors Registry.
    Creates a new page only when no match is found. After processing all actors, updates the
    Event page's Key Actors relation with all resolved page IDs.

    Returns a list of (page_id, page_url, actor_name, is_new) tuples.
    """
    client = _get_client()
    results: list[tuple[str, str, str, bool]] = []

    for actor in actors:
        name: str = actor.get("name", "").strip()
        if not name:
            continue

        existing = _find_actor_by_name(client, name)
        if existing:
            page_id, page_url = existing
            console.print(f"[dim]Actor already exists:[/dim] {name} — skipping")
            results.append((page_id, page_url, name, False))
        else:
            page_id, page_url = _create_actor(client, actor)
            console.print(f"[green]Actor created:[/green] {name}")
            results.append((page_id, page_url, name, True))

    if results:
        actor_ids = [page_id for page_id, _, _, _ in results]
        _link_actors_to_event(client, event_page_id, actor_ids)

    return results


def write_activity_log(
    log_title: str,
    summary: str,
    action_type: str,
    target_database: str,
    target_record: str = "",
    source_material: str = "",
    confidence: str = "High",
    notes: str = "",
    requires_human_review: bool = False,
) -> tuple[str, str]:
    """Create an entry in the Agent Activity Log database.

    Returns (page_id, page_url).
    Raises RuntimeError on API failure.
    """
    client = _get_client()

    properties: dict[str, Any] = {
        "Log Title": _title(log_title),
        "Agent ID": _select("Agent-A: Ingestion"),
        "Action Type": _select(action_type),
        "Target Database": _select(target_database),
        "Status": _select("Completed"),
        "Confidence": _select(confidence),
        "Summary": _rich_text(summary),
        "Target Record": _rich_text(target_record),
        "Source Material": _rich_text(source_material),
        "Notes": _rich_text(notes),
        "Requires Human Review": {"checkbox": requires_human_review},
        "Visibility": _select("Internal"),
        "Timestamp": {"date": {"start": datetime.date.today().isoformat()}},
    }

    try:
        response = client.pages.create(
            parent={"database_id": NOTION_ACTIVITY_LOG_DB_ID},
            properties=properties,
        )
    except APIResponseError as exc:
        raise RuntimeError(
            f"Notion API error writing Activity Log record: {exc.status} — {exc.body}"
        ) from exc

    page_id = response["id"]
    page_url = response.get("url", f"https://notion.so/{page_id.replace('-', '')}")
    return page_id, page_url


def _find_actor_by_name(client: Client, name: str) -> tuple[str, str] | None:
    """Search for an actor by name in the Actors Registry. Returns (page_id, page_url) or None."""
    try:
        response = client.databases.query(
            database_id=NOTION_ACTORS_DB_ID,
            filter={
                "property": "Name",
                "title": {
                    "equals": name
                }
            }
        )
    except APIResponseError as exc:
        raise RuntimeError(
            f"Notion API error querying Actors Registry for '{name}': {exc.status} — {exc.body}"
        ) from exc

    results = response.get("results", [])
    if not results:
        return None

    page = results[0]
    page_id = page["id"]
    page_url = page.get("url", f"https://notion.so/{page_id.replace('-', '')}")
    return page_id, page_url


def _create_actor(client: Client, actor: dict[str, Any]) -> tuple[str, str]:
    """Create a new page in the Actors Registry. Returns (page_id, page_url)."""
    name = actor.get("name", "Unknown Actor")
    raw_actor_type = actor.get("actor_type", "Non-State")
    notion_actor_type = ACTOR_TYPE_NOTION_MAP.get(raw_actor_type, raw_actor_type)
    iso3 = actor.get("iso3")
    role_in_event = actor.get("role_in_event", "")

    properties: dict[str, Any] = {
        "Name": _title(name),
        "Actor Type": _select(notion_actor_type),
        "Notes": _rich_text(role_in_event),
    }
    if iso3:
        properties["ISO3 / Identifier"] = _rich_text(iso3)

    try:
        response = client.pages.create(
            parent={"database_id": NOTION_ACTORS_DB_ID},
            properties=properties,
        )
    except APIResponseError as exc:
        raise RuntimeError(
            f"Notion API error creating Actor '{name}': {exc.status} — {exc.body}"
        ) from exc

    page_id = response["id"]
    page_url = response.get("url", f"https://notion.so/{page_id.replace('-', '')}")
    return page_id, page_url


def _link_actors_to_event(
    client: Client, event_page_id: str, actor_page_ids: list[str]
) -> None:
    """Update the Event page to set the Key Actors relation."""
    try:
        client.pages.update(
            page_id=event_page_id,
            properties={
                "Key Actors": {
                    "relation": [{"id": pid} for pid in actor_page_ids]
                }
            },
        )
    except APIResponseError as exc:
        raise RuntimeError(
            f"Notion API error linking actors to event {event_page_id}: {exc.status} — {exc.body}"
        ) from exc


def _get_client() -> Client:
    return Client(auth=NOTION_API_KEY)


# ── Property helpers ──────────────────────────────────────────────────────────

def _title(text: str) -> dict:
    return {"title": [{"text": {"content": text[:2000]}}]}


def _rich_text(text: str) -> dict:
    # Notion rich_text blocks have a 2000-char limit per element
    chunks = [text[i:i + 2000] for i in range(0, max(len(text), 1), 2000)]
    return {"rich_text": [{"text": {"content": chunk}} for chunk in chunks]}


def _select(value: str) -> dict:
    return {"select": {"name": value}}


def _date(iso_date: str) -> dict:
    return {"date": {"start": iso_date}}
