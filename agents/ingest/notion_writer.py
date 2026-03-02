"""Notion API writes for Sources, Events, Intelligence Feeds, and Actors Registry databases."""

import datetime
import requests
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

_NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_API_KEY}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}


# ── Deduplication ─────────────────────────────────────────────────────────────

def find_existing_source(url: str) -> tuple[str, str] | None:
    """Check if a source with this URL already exists in the Sources database.

    Returns (page_id, page_url) if found, None otherwise.
    Only runs when a URL is present — text-only ingestions skip this.
    """
    if not url:
        return None

    query_url = f"https://api.notion.com/v1/databases/{NOTION_SOURCES_DB_ID}/query"
    payload = {
        "filter": {
            "property": "URL",
            "url": {"equals": url},
        }
    }

    try:
        response = requests.post(query_url, headers=_NOTION_HEADERS, json=payload, timeout=15)
        response.raise_for_status()
        results = response.json().get("results", [])
        if not results:
            return None
        page = results[0]
        page_id = page["id"]
        page_url = page.get("url", f"https://notion.so/{page_id.replace('-', '')}")
        return page_id, page_url
    except Exception:
        return None


def find_existing_event(event_name: str, event_date: str) -> tuple[str, str] | None:
    """Check if an event with this name and date already exists in the Events database.

    Matches on exact event name (title) — date is used as an additional filter
    to avoid false positives on generically named events.
    Returns (page_id, page_url) if found, None otherwise.
    """
    if not event_name:
        return None

    query_url = f"https://api.notion.com/v1/databases/{NOTION_EVENTS_DB_ID}/query"

    # Filter by title text match; date filtering would require a compound filter
    # which isn't reliable on the title property. We post-filter by date below.
    payload = {
        "filter": {
            "property": "Event Name",
            "title": {"equals": event_name},
        }
    }

    try:
        response = requests.post(query_url, headers=_NOTION_HEADERS, json=payload, timeout=15)
        response.raise_for_status()
        results = response.json().get("results", [])

        for page in results:
            props = page.get("properties", {})
            date_prop = props.get("Date", {}).get("date") or {}
            page_date = date_prop.get("start", "")
            # Match on name alone if no date provided; match name+date if both present
            if not event_date or not page_date or page_date == event_date:
                page_id = page["id"]
                page_url = page.get("url", f"https://notion.so/{page_id.replace('-', '')}")
                return page_id, page_url

        return None
    except Exception:
        return None


# ── Writers ───────────────────────────────────────────────────────────────────

def write_source(source: dict[str, Any]) -> tuple[str, str]:
    """Create a Source record in Notion, skipping if URL already exists.

    Returns (page_id, page_url).
    Raises RuntimeError on API failure.
    """
    # Dedup check — only when a URL is present
    url = source.get("url")
    if url:
        existing = find_existing_source(url)
        if existing:
            page_id, page_url = existing
            console.print(f"[dim]Source already exists (URL match):[/dim] {url} — skipping")
            return page_id, page_url

    client = _get_client()

    properties = {
        "Title": _title(source.get("title", "Untitled")),
        "Source Type": _select(source.get("source_type", "Other")),
        "Reliability": _select(source.get("reliability", "Medium")),
        "Author / Organization": _rich_text(source.get("author_organization", "")),
        "Summary": _rich_text(source.get("summary", "")),
    }

    if url:
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
    """Create an Event record in Notion, skipping if name+date already exists.

    Returns (page_id, page_url).
    Raises RuntimeError on API failure.
    """
    event_name = event.get("event_name", "Untitled Event")
    event_date = event.get("date", "")

    # Dedup check
    existing = find_existing_event(event_name, event_date)
    if existing:
        page_id, page_url = existing
        console.print(
            f"[dim]Event already exists (name+date match):[/dim] {event_name} ({event_date}) — skipping"
        )
        return page_id, page_url

    client = _get_client()

    properties = {
        "Event Name": _title(event_name),
        "Event Type": _select(event.get("event_type", "Other")),
        "Description": _rich_text(event.get("description", "")),
        "PF Signal": _select(event.get("pf_signal", "Indirect")),
        "Key Sources": {"relation": [{"id": source_page_id}]},
    }

    if event_date:
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


_PF_SIGNAL_MAP: dict[str, str] = {
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

    raw_gap = event.get("pf_signal", "Indirect")
    gap_implication = _PF_SIGNAL_MAP.get(raw_gap, "Unclear")

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
        "PF Signal": _select(gap_implication),
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
    article_title: str,
    screening_score: int | None = None,
    screening_verdict: str | None = None,
    databases_written: list[str] | None = None,
    actor_count: int = 0,
    status: str = "Completed",
    notes: str = "",
) -> tuple[str, str] | None:
    """Write a record to the Agent Activity Log database. Never raises."""
    try:
        client = _get_client()
        now_utc = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")

        full_properties: dict[str, Any] = {
            "Log Title": _title(article_title),
            "Agent ID": _select("Agent-A: Ingestion"),
            "Action Type": _select("Ingest"),
            "Timestamp": {"date": {"start": now_utc}},
            "Status": _select(status),
            "Actor Count": {"number": actor_count},
            "Visibility": _select("Internal"),
        }

        if screening_score is not None:
            full_properties["Screening Score"] = {"number": screening_score}
        if screening_verdict:
            full_properties["Screening Verdict"] = _rich_text(screening_verdict)
        if databases_written:
            full_properties["Summary"] = _rich_text(
                "Wrote to: " + ", ".join(databases_written)
            )
        if notes:
            full_properties["Notes"] = _rich_text(notes)

        core_properties: dict[str, Any] = {
            k: full_properties[k]
            for k in ("Log Title", "Timestamp", "Status")
            if k in full_properties
        }
        if notes:
            core_properties["Notes"] = full_properties["Notes"]

        try:
            response = client.pages.create(
                parent={"database_id": NOTION_ACTIVITY_LOG_DB_ID},
                properties=full_properties,
            )
        except APIResponseError:
            response = client.pages.create(
                parent={"database_id": NOTION_ACTIVITY_LOG_DB_ID},
                properties=core_properties,
            )

        page_id = response["id"]
        page_url = response.get("url", f"https://notion.so/{page_id.replace('-', '')}")
        return page_id, page_url

    except Exception as exc:
        console.print(f"[yellow]⚠ Activity log write skipped:[/yellow] {exc}")
        return None


def _find_actor_by_name(client: Client, name: str) -> tuple[str, str] | None:
    """Search for an actor by exact name in the Actors Registry."""
    url = f"https://api.notion.com/v1/databases/{NOTION_ACTORS_DB_ID}/query"
    payload = {
        "filter": {
            "property": "Name",
            "title": {"equals": name},
        }
    }

    try:
        response = requests.post(url, headers=_NOTION_HEADERS, json=payload, timeout=30)
        response.raise_for_status()
    except requests.exceptions.RequestException as exc:
        raise RuntimeError(
            f"Notion API error querying Actors Registry for '{name}': {exc}"
        ) from exc

    results = response.json().get("results", [])
    if not results:
        return None

    page = results[0]
    page_id = page["id"]
    page_url = page.get("url", f"https://notion.so/{page_id.replace('-', '')}")
    return page_id, page_url


def _create_actor(client: Client, actor: dict[str, Any]) -> tuple[str, str]:
    """Create a new page in the Actors Registry."""
    name = actor.get("name", "Unknown Actor")
    raw_actor_type = actor.get("actor_type", "Non-State")
    notion_actor_type = ACTOR_TYPE_NOTION_MAP.get(raw_actor_type, raw_actor_type)
    iso3 = actor.get("iso3")
    role_in_event = actor.get("role_in_event", "")
    sub_type = actor.get("sub_type")

    properties: dict[str, Any] = {
        "Name": _title(name),
        "Actor Type": _select(notion_actor_type),
        "Notes": _rich_text(role_in_event),
        "Status": _select("Active"),
        "Visibility": _select("Internal"),
    }
    if iso3:
        properties["ISO3 / Identifier"] = _rich_text(iso3)
    if sub_type:
        properties["Sub-Type"] = _select(sub_type)

    pf_score_properties = {
        "Authority Score": {"number": None},
        "Reach Score": {"number": None},
    }

    try:
        response = client.pages.create(
            parent={"database_id": NOTION_ACTORS_DB_ID},
            properties={**properties, **pf_score_properties},
        )
    except APIResponseError:
        console.print(
            f"[yellow]Warning:[/yellow] Could not write PF Score fields for "
            f"'{name}' — retrying without them."
        )
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
    chunks = [text[i:i + 2000] for i in range(0, max(len(text), 1), 2000)]
    return {"rich_text": [{"text": {"content": chunk}} for chunk in chunks]}


def _select(value: str) -> dict:
    return {"select": {"name": value}}


def _date(iso_date: str) -> dict:
    return {"date": {"start": iso_date}}
