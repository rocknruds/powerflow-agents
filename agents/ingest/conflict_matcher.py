"""Conflict matching step for the PowerFlow ingestion pipeline.

After an event is ingested, matches it against the Global Conflicts Registry using
Claude and links matching conflicts to the event via the "Linked Conflicts" relation.
"""

import json
import re

import anthropic
import requests
from rich.console import Console

from config.settings import ANTHROPIC_API_KEY, NOTION_API_KEY

console = Console()

_CONFLICTS_DB_ID = "db9f622892a74cdd942981c330e90886"
_NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_API_KEY}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}
_CLAUDE_MODEL = "claude-haiku-4-5-20251001"
_SYSTEM_PROMPT = (
    "You are matching a geopolitical event to conflicts in a registry. "
    "Return ONLY a JSON array of conflict names that this event directly relates to. "
    "Return an empty array [] if no match. Be conservative — only match when the "
    "connection is clear and direct, not merely thematic."
)


def fetch_conflicts() -> list[dict]:
    """Query the Global Conflicts Registry and return a list of conflict summaries.

    Each dict has keys: page_id, name, primary_actors, region, type.
    Returns an empty list silently on any error.
    """
    try:
        url = f"https://api.notion.com/v1/databases/{_CONFLICTS_DB_ID}/query"
        results = []
        has_more = True
        start_cursor = None

        while has_more:
            payload: dict = {}
            if start_cursor:
                payload["start_cursor"] = start_cursor

            resp = requests.post(
                url, headers=_NOTION_HEADERS, json=payload, timeout=30
            )
            resp.raise_for_status()
            body = resp.json()

            for page in body.get("results", []):
                props = page.get("properties", {})

                name_prop = props.get("Conflict Name", {})
                title_parts = name_prop.get("title", [])
                name = "".join(t.get("plain_text", "") for t in title_parts).strip()
                if not name:
                    continue

                actors_prop = props.get("Primary Actors", {})
                actors_parts = actors_prop.get("rich_text", [])
                primary_actors = "".join(
                    t.get("plain_text", "") for t in actors_parts
                ).strip()

                region_prop = props.get("Region", {})
                region = (region_prop.get("select") or {}).get("name", "")

                type_prop = props.get("Type", {})
                conflict_type = (type_prop.get("select") or {}).get("name", "")

                results.append(
                    {
                        "page_id": page["id"],
                        "name": name,
                        "primary_actors": primary_actors,
                        "region": region,
                        "type": conflict_type,
                    }
                )

            has_more = body.get("has_more", False)
            start_cursor = body.get("next_cursor")

        return results

    except Exception:
        return []


def match_conflicts(
    event: dict, actors: list[dict], conflicts: list[dict]
) -> list[str]:
    """Use Claude to match an event+actors against the conflicts list.

    Returns a list of matching conflict page_ids.
    Returns [] if conflicts is empty, Claude fails, or JSON is malformed.
    """
    if not conflicts:
        return []

    try:
        actor_names = ", ".join(
            a.get("name", "") for a in actors if a.get("name")
        ) or "none"

        conflict_lines = "\n".join(
            f"{i + 1}. {c['name']} | Region: {c['region']} | "
            f"Type: {c['type']} | Primary Actors: {c['primary_actors']}"
            for i, c in enumerate(conflicts)
        )

        user_msg = (
            f"EVENT: {event.get('event_name', 'Unknown')}\n"
            f"DESCRIPTION: {event.get('description', '')}\n"
            f"ACTORS INVOLVED: {actor_names}\n\n"
            f"CONFLICTS REGISTRY:\n{conflict_lines}\n\n"
            "Return a JSON array of conflict names from the list above that "
            "this event directly relates to. Return [] if none clearly apply."
        )

        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        message = client.messages.create(
            model=_CLAUDE_MODEL,
            max_tokens=512,
            system=[
                {
                    "type": "text",
                    "text": _SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = message.content[0].text.strip()

        cleaned = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()
        matched_names: list[str] = json.loads(cleaned)

        name_to_id = {c["name"].lower(): c["page_id"] for c in conflicts}
        page_ids = [
            name_to_id[n.lower()]
            for n in matched_names
            if isinstance(n, str) and n.lower() in name_to_id
        ]
        return page_ids

    except Exception:
        return []


def link_conflicts_to_event(
    event_page_id: str, conflict_page_ids: list[str]
) -> None:
    """PATCH the event page to set its 'Linked Conflicts' relation.

    Never raises — failures are printed as warnings.
    """
    try:
        url = f"https://api.notion.com/v1/pages/{event_page_id}"
        payload = {
            "properties": {
                "Linked Conflicts": {
                    "relation": [{"id": pid} for pid in conflict_page_ids]
                }
            }
        }
        resp = requests.patch(url, headers=_NOTION_HEADERS, json=payload, timeout=30)
        resp.raise_for_status()
    except Exception as exc:
        console.print(f"[yellow]⚠ Warning:[/yellow] Could not link conflicts to event: {exc}")


def run_conflict_matching(
    event_page_id: str, event: dict, actors: list[dict]
) -> list[str]:
    """Orchestrate fetch → match → link for a single ingested event.

    Returns a list of matched conflict names for display purposes.
    Never raises — returns [] and prints a warning on any failure.
    """
    try:
        conflicts = fetch_conflicts()
        matched_ids = match_conflicts(event, actors, conflicts)

        if matched_ids:
            link_conflicts_to_event(event_page_id, matched_ids)
            id_to_name = {c["page_id"]: c["name"] for c in conflicts}
            matched_names = [id_to_name.get(pid, pid) for pid in matched_ids]
            console.print(
                f"[green]✓[/green] Linked to {len(matched_ids)} conflict(s): "
                + ", ".join(matched_names)
            )
            return matched_names
        else:
            console.print("[dim]No conflict match found.[/dim]")
            return []

    except Exception as exc:
        console.print(f"[yellow]⚠ Warning:[/yellow] Conflict matching failed: {exc}")
        return []
