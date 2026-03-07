"""Notion API writes for Sources, Events, Intelligence Feeds, and Actors Registry databases."""

import datetime
import re
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
    NOTION_INDIVIDUALS_DB_ID,
    NOTION_INTEL_FEEDS_DB_ID,
    NOTION_SOURCES_DB_ID,
)

console = Console()

_EST = datetime.timezone(datetime.timedelta(hours=-5))

# ── Author normalization ───────────────────────────────────────────────────────

_PUBLICATION_MAP: list[tuple[tuple[str, ...], str]] = [
    (("york times", "nytimes", "nyt"), "NYT"),
    (("wall street journal", "wsj"), "WSJ"),
    (("washington post", "wapo"), "Washington Post"),
    (("reuters",), "Reuters"),
    (("associated press", " ap "), "AP"),
    (("csis",), "CSIS"),
    (("rand",), "RAND"),
    (("carnegie",), "Carnegie Endowment"),
    (("crisis group",), "ICG"),
]


def _normalize_author(raw: str | None) -> str | None:
    """Return a canonical publication name, or None if the value looks like a personal name.

    Matches known publication variants case-insensitively. If the value contains a
    space but matches no known publication keyword, it is treated as a personal byline
    and dropped with a warning so the extraction prompt can be improved.
    """
    if not raw or not raw.strip():
        return None
    lower = raw.lower()
    for keywords, canonical in _PUBLICATION_MAP:
        if any(kw in lower for kw in keywords):
            return canonical
    # Heuristic: a value with a space and no publication match is likely a person's name
    if " " in raw.strip():
        console.print(
            f"[yellow]Warning:[/yellow] Author value '{raw}' looks like a personal name "
            "— omitting from Author field. Update the extraction prompt if this recurs."
        )
        return None
    return raw.strip()


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
        "Publication / Organization": _rich_text(source.get("publication", "")),
        "Author": _rich_text(source.get("author", "")),
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
        "PF Signal": _select(event.get("pf_signal", "Unclear")),
        "Key Sources": {"relation": [{"id": source_page_id}]},
    }

    if event_date:
        properties["Date"] = _date(event_date)
    if mechanism := event.get("mechanism"):
        properties["Mechanism"] = _rich_text(mechanism)
    if trajectory := event.get("trajectory"):
        properties["Trajectory"] = _rich_text(trajectory)

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


_SOURCE_TYPE_MAP: dict[str, str] = {
    "Think tank": "Think Tank",
}


def write_intel_feed(
    source: dict[str, Any],
    event: dict[str, Any],
    screen_result: dict[str, Any],
    intel_feed: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """Create an Intelligence Feed record in Notion.

    Returns (page_id, page_url).
    Raises RuntimeError on API failure.
    """
    client = _get_client()

    raw_source_type = source.get("source_type", "Other")
    source_type = _SOURCE_TYPE_MAP.get(raw_source_type, raw_source_type)

    gap_implication = event.get("pf_signal", "Unclear")

    score: int = screen_result.get("score", 0)
    if score >= 80:
        confidence_shift = "Major Update"
    elif score >= 60:
        confidence_shift = "Minor Update"
    elif score >= 40:
        confidence_shift = "Confirms Existing"
    else:
        confidence_shift = "New Thread"

    feed = intel_feed or {}
    normalized_author = _normalize_author(source.get("publication"))
    today = datetime.datetime.now(_EST).strftime("%Y-%m-%d")

    properties: dict[str, Any] = {
        "Title": _title(source.get("title", "Untitled")),
        "Source Type": _select(source_type),
        "Reliability": _select(source.get("reliability", "Medium")),
        "Author": _rich_text(normalized_author or ""),
        "PF Signal": _select(gap_implication),
        "So What Summary": _rich_text(feed.get("so_what_summary", "")),
        "Confidence Shift": _select(confidence_shift),
        "Ingestion Status": _select("Integrated"),
        "Agent Processed": {"checkbox": True},
        "Date Ingested": _date(today),
    }

    if pub_date := source.get("publication_date"):
        properties["Publication Date"] = _date(pub_date)

    if analyst_affiliation := feed.get("analyst_affiliation"):
        properties["Analyst Affiliation"] = _rich_text(analyst_affiliation)
    if mechanism := feed.get("mechanism"):
        properties["Mechanism"] = _rich_text(mechanism)
    if trajectory := feed.get("trajectory"):
        properties["Trajectory"] = _rich_text(trajectory)
    if cascade_effects := feed.get("cascade_effects"):
        properties["Cascade Effects"] = _rich_text(cascade_effects)

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


_NOTION_HEX_RE = re.compile(r"[0-9a-f]{32}", re.IGNORECASE)


def _extract_notion_page_id(url_or_id: str) -> str:
    """Return the bare 32-char hex Notion page ID from a URL or raw ID.

    Accepts:
    - Dashed UUID:  '316f8ae9-4162-8189-a98a-d74ed8097635'
    - Bare hex ID:  '316f8ae941628189a98ad74ed8097635'
    - Notion URL:   'https://www.notion.so/Title-316f8ae941628189a98ad74ed8097635'

    Raises ValueError if no valid 32-char hex ID is found.
    """
    # Strip dashes so UUID-format IDs become a solid 32-char hex string
    stripped = url_or_id.replace("-", "")
    matches = _NOTION_HEX_RE.findall(stripped)
    if not matches:
        raise ValueError(f"No valid Notion page ID found in: {url_or_id!r}")
    page_id = matches[-1].lower()
    assert len(page_id) == 32, f"Extracted ID is not 32 chars: {page_id!r}"
    return page_id


def patch_intel_feed(
    intel_page_id: str,
    actor_page_ids: list[str],
    source_page_id: str,
    event_page_id: str,
) -> None:
    """Back-fill relation fields on the Intel Feed entry after all writes complete.

    Populates:
    - Actors Involved: relation to Actors Registry pages
    - Source: relation to the Source entry
    - Linked Records: relation to the Event entry

    Never raises — a failure here is logged but does not abort the run.
    """
    client = _get_client()

    try:
        source_id = _extract_notion_page_id(source_page_id)
        event_id = _extract_notion_page_id(event_page_id)
    except ValueError as exc:
        console.print(f"[yellow]⚠ Intel Feed patch skipped:[/yellow] bad page ID — {exc}")
        return

    properties: dict[str, Any] = {
        "Source": {"relation": [{"id": source_id}]},
        "Linked Records": {"relation": [{"id": event_id}]},
    }

    if actor_page_ids:
        valid_actor_ids: list[str] = []
        for raw in actor_page_ids:
            try:
                valid_actor_ids.append(_extract_notion_page_id(raw))
            except ValueError as exc:
                console.print(f"[yellow]⚠ Skipping malformed actor ID:[/yellow] {exc}")
        if valid_actor_ids:
            properties["Actors Involved"] = {
                "relation": [{"id": pid} for pid in valid_actor_ids]
            }

    try:
        client.pages.update(page_id=intel_page_id, properties=properties)
        console.print("[green]✓[/green] Intel Feed back-filled (Actors Involved, Source, Linked Records).")
    except APIResponseError as exc:
        console.print(
            f"[yellow]⚠ Intel Feed patch skipped:[/yellow] {exc.status} — {exc.body}"
        )
    except Exception as exc:
        console.print(f"[yellow]⚠ Intel Feed patch skipped:[/yellow] {exc}")


def write_actors(
    actors: list[dict[str, Any]], event_page_id: str
) -> list[tuple[str, str, str, bool, bool]]:
    """Create or find Actor records in the Actors Registry.

    All actor types — including named Individual actors being scored — are
    written to Actors Registry. Influential Individuals DB is reserved for
    manually-curated figures who are NOT being scored by the agent.

    Returns a list of (page_id, page_url, actor_name, is_new, from_registry) tuples.
    """
    client = _get_client()
    results: list[tuple[str, str, str, bool, bool]] = []
    registry_page_ids: list[str] = []

    for actor in actors:
        name: str = actor.get("name", "").strip()
        if not name:
            continue

        existing = _find_actor_by_name(client, name)
        if existing:
            page_id, page_url = existing
            console.print(f"[dim]Actor already exists:[/dim] {name} — skipping")
            results.append((page_id, page_url, name, False, True))
            registry_page_ids.append(page_id)
        else:
            page_id, page_url = _create_actor(client, actor)
            console.print(f"[green]Actor created:[/green] {name}")
            results.append((page_id, page_url, name, True, True))
            registry_page_ids.append(page_id)

    if registry_page_ids:
        _link_actors_to_event(client, event_page_id, registry_page_ids)

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
        now_utc = datetime.datetime.now(_EST).isoformat(timespec="seconds")

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


def _find_individual_by_name(client: Client, name: str) -> tuple[str, str] | None:
    """Search for an individual by exact name in the Influential Individuals database."""
    url = f"https://api.notion.com/v1/databases/{NOTION_INDIVIDUALS_DB_ID}/query"
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
            f"Notion API error querying Influential Individuals for '{name}': {exc}"
        ) from exc

    results = response.json().get("results", [])
    if not results:
        return None

    page = results[0]
    page_id = page["id"]
    page_url = page.get("url", f"https://notion.so/{page_id.replace('-', '')}")
    return page_id, page_url


def _create_individual(client: Client, actor: dict[str, Any]) -> tuple[str, str]:
    """Create a new page in the Influential Individuals database."""
    name = actor.get("name", "Unknown")
    today = datetime.datetime.now(_EST).strftime("%Y-%m-%d")

    properties: dict[str, Any] = {
        "Name": _title(name),
        "Role": _rich_text(actor.get("role_in_event", "")),
        "Status": _select("Active"),
        "Visibility": _select("Internal"),
        "Agent Source": _rich_text("Ingestion Agent"),
        "Influence Type": {"multi_select": [{"name": "Decision Authority"}]},
        "Last Updated": _date(today),
    }

    if analytical_notes := actor.get("analytical_notes"):
        properties["Analytical Notes"] = _rich_text(analytical_notes)
    if pf_relevance := actor.get("pf_relevance"):
        properties["PF Relevance"] = _rich_text(pf_relevance)

    try:
        response = client.pages.create(
            parent={"database_id": NOTION_INDIVIDUALS_DB_ID},
            properties=properties,
        )
    except APIResponseError as exc:
        raise RuntimeError(
            f"Notion API error creating Individual '{name}': {exc.status} — {exc.body}"
        ) from exc

    page_id = response["id"]
    page_url = response.get("url", f"https://notion.so/{page_id.replace('-', '')}")
    return page_id, page_url


def _write_individual(
    client: Client, actor: dict[str, Any]
) -> tuple[str, str, bool]:
    """Dedup by name, then create Individual in Influential Individuals DB. Returns (page_id, page_url, is_new)."""
    name = actor.get("name", "").strip() or "Unknown"
    existing = _find_individual_by_name(client, name)
    if existing:
        page_id, page_url = existing
        return page_id, page_url, False
    page_id, page_url = _create_individual(client, actor)
    return page_id, page_url, True


_VALID_REGIONS = ("Europe", "Middle East", "Africa", "Americas", "Asia-Pacific", "Global", "Eurasia")

_REGION_COERCE_MAP: dict[str, str] = {
    # Europe variants
    "western europe": "Europe",
    "eastern europe": "Europe",
    "northern europe": "Europe",
    "southern europe": "Europe",
    "central europe": "Europe",
    "balkans": "Europe",
    # Middle East variants
    "near east": "Middle East",
    "gulf": "Middle East",
    "levant": "Middle East",
    "arabian peninsula": "Middle East",
    "mena": "Middle East",
    # Africa variants
    "sub-saharan africa": "Africa",
    "north africa": "Africa",
    "west africa": "Africa",
    "east africa": "Africa",
    "southern africa": "Africa",
    "central africa": "Africa",
    # Americas variants
    "north america": "Americas",
    "south america": "Americas",
    "latin america": "Americas",
    "central america": "Americas",
    "caribbean": "Americas",
    # Asia-Pacific variants
    "east asia": "Asia-Pacific",
    "southeast asia": "Asia-Pacific",
    "south asia": "Asia-Pacific",
    "pacific": "Asia-Pacific",
    "oceania": "Asia-Pacific",
    "indo-pacific": "Asia-Pacific",
    # Eurasia variants
    "central asia": "Eurasia",
    "caucasus": "Eurasia",
    "post-soviet": "Eurasia",
    "former soviet": "Eurasia",
}


def _coerce_region(raw: str) -> str:
    """Map a raw region string to the nearest valid Notion select option."""
    if not raw:
        return "Global"
    normalised = raw.strip().lower()
    # Exact match (case-insensitive)
    for valid in _VALID_REGIONS:
        if normalised == valid.lower():
            return valid
    # Lookup in coercion map
    if normalised in _REGION_COERCE_MAP:
        return _REGION_COERCE_MAP[normalised]
    # Substring fallback: check if any valid option appears inside the raw string
    for valid in _VALID_REGIONS:
        if valid.lower() in normalised:
            return valid
    return "Global"


def _create_actor(client: Client, actor: dict[str, Any]) -> tuple[str, str]:
    """Create a new page in the Actors Registry with all available fields populated."""
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
        "Agent Source": _rich_text("Ingestion Agent"),
        "Requires Human Review": {"checkbox": True},
    }
    if iso3:
        properties["ISO3 / Identifier"] = _rich_text(iso3)
    if sub_type:
        properties["Sub-Type"] = _select(sub_type)
    if region := actor.get("region"):
        properties["Region"] = _select(_coerce_region(region))
    if pf_vector := actor.get("pf_vector"):
        properties["PF Vector"] = _select(pf_vector)
    if proxy_depth := actor.get("proxy_depth"):
        properties["Proxy Depth"] = _select(proxy_depth)
    capabilities: list[str] = actor.get("capabilities") or []
    if capabilities:
        properties["Capabilities"] = {"multi_select": [{"name": c} for c in capabilities]}

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
