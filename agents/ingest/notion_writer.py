"""Notion API writes for Sources and Events databases."""

from typing import Any

from notion_client import Client
from notion_client.errors import APIResponseError
from rich.console import Console

from config.settings import (
    NOTION_API_KEY,
    NOTION_EVENTS_DB_ID,
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
