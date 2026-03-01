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
        # NOTE: Notion property must be renamed from "Impact on Sovereignty Gap" to "PF Signal"
        # in the Events Timeline database settings before this will write correctly.
        "PF Signal": _select(
            event.get("pf_signal", "Indirect")
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
    article_title: str,
    screening_score: int | None = None,
    screening_verdict: str | None = None,
    databases_written: list[str] | None = None,
    actor_count: int = 0,
    status: str = "Completed",
    notes: str = "",
) -> tuple[str, str] | None:
    """Write a record to the Agent Activity Log database after an ingestion run.

    Logs ingestion metadata — title, score, verdict, actor count, databases touched,
    and status (``"Completed"`` or ``"Rejected"``). Pass ``notes`` to capture error messages
    on failure.

    Returns ``(page_id, page_url)`` on success, or ``None`` on any failure.
    Never raises — a logging failure must never crash an ingestion run.
    """
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

        # Minimal set of fields that are most likely to exist in any version of the schema.
        # Used as a fallback if the full write is rejected due to unknown properties.
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
            # Retry with only core fields if the schema doesn't support some properties.
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
    """Search for an actor by name in the Actors Registry. Returns (page_id, page_url) or None."""
    url = f"https://api.notion.com/v1/databases/{NOTION_ACTORS_DB_ID}/query"
    headers = {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28",
    }
    payload = {
        "filter": {
            "property": "Name",
            "title": {
                "equals": name
            }
        }
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=15)
        response.raise_for_status()
    except requests.exceptions.RequestException as exc:
        raise RuntimeError(
            f"Notion API error querying Actors Registry for '{name}': {exc}"
        ) from exc

    data = response.json()
    results = data.get("results", [])
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

    pf_score_properties = {
        "Authority Score": {"number": None},  # 0-100, populated by PF Score Agent
        "Reach Score": {"number": None},       # 0-100, populated by PF Score Agent
    }

    try:
        response = client.pages.create(
            parent={"database_id": NOTION_ACTORS_DB_ID},
            properties={**properties, **pf_score_properties},
        )
    except APIResponseError:
        console.print(
            f"[yellow]Warning:[/yellow] Could not write Authority Score / Reach Score for "
            f"'{name}' — schema fields may not exist yet. Retrying without PF Score fields."
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
    # Notion rich_text blocks have a 2000-char limit per element
    chunks = [text[i:i + 2000] for i in range(0, max(len(text), 1), 2000)]
    return {"rich_text": [{"text": {"content": chunk}} for chunk in chunks]}


def _select(value: str) -> dict:
    return {"select": {"name": value}}


def _date(iso_date: str) -> dict:
    return {"date": {"start": iso_date}}
