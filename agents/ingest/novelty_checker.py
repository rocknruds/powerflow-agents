"""Novelty check — compares incoming article against existing Intel Feeds."""

import json
import os
import re

import anthropic
import requests
from rich.console import Console

from config.settings import ANTHROPIC_API_KEY, CLAUDE_MODEL

console = Console()

NOTION_API_KEY = os.environ.get("NOTION_API_KEY")
INTEL_FEEDS_DB_ID = "3835cb822ae441a5a18cb4271d9fe955"
NOTION_VERSION = "2022-06-28"

NOVELTY_VERDICTS = {"New Signal", "Confirming", "Redundant"}

_NOVELTY_SYSTEM_PROMPT = """\
You are a geopolitical intelligence analyst working within the PowerFlow system. 
Your job is to assess whether an incoming article adds new analytical value 
to the existing intelligence database.

You will be given:
1. A summary of the incoming article (title, source, key argument)
2. A list of existing Intel Feed entries covering the same actors or region

Assess novelty across three dimensions:
- CAUSAL ARGUMENT: Does the article make a causal argument not already documented?
- TRAJECTORY: Does it update or contradict an existing trajectory or recovery assessment?
- ACTOR COVERAGE: Does it cover an actor or dynamic not yet represented in the feeds?

Return ONLY a valid JSON object:
{
  "verdict": "New Signal | Confirming | Redundant",
  "novelty_score": <integer 0-100>,
  "reasoning": "string (2-3 sentences explaining the verdict)",
  "new_elements": "string (what specifically is new, if anything — null if Redundant)"
}

Verdict definitions:
- New Signal: Adds a new causal argument, updates a trajectory, covers a new actor, 
  or meaningfully contradicts existing assessments. Ingest fully.
- Confirming: Same core argument as existing entries but from a different source 
  or with minor additional detail. Log source only, skip full Intel Feed write.
- Redundant: No new analytical value. Exact same argument already well-documented. 
  Discard recommended.

Be conservative with Redundant — when in doubt, use Confirming.
"""


def fetch_existing_feeds(actors: list[str], region_tags: list[str], max_results: int = 8) -> list[dict]:
    """Query Intel Feeds DB for entries matching actors or region tags."""
    headers = {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }

    # "Actors Involved" is now a relation field — cannot be searched as plain text.
    # Fall back to matching actor names against the Title and So What Summary text fields.
    actor_title_filters = [
        {
            "property": "Title",
            "title": {"contains": actor},
        }
        for actor in actors[:4]
    ]
    actor_so_what_filters = [
        {
            "property": "So What Summary",
            "rich_text": {"contains": actor},
        }
        for actor in actors[:4]
    ]

    region_filters = [
        {
            "property": "Region Tags",
            "multi_select": {"contains": tag},
        }
        for tag in region_tags[:3]
    ]

    all_filters = actor_title_filters + actor_so_what_filters + region_filters
    if not all_filters:
        return []

    payload = {
        "filter": {"or": all_filters},
        "page_size": max_results,
        "sorts": [{"timestamp": "created_time", "direction": "descending"}],
    }

    resp = requests.post(
        f"https://api.notion.com/v1/databases/{INTEL_FEEDS_DB_ID}/query",
        headers=headers,
        json=payload,
        timeout=15,
    )

    if not resp.ok:
        console.print(f"[yellow]Warning:[/yellow] Intel Feeds query failed: {resp.status_code}")
        return []

    results = resp.json().get("results", [])
    feeds = []
    for r in results:
        props = r.get("properties", {})
        title = _get_title(props, "Title")
        so_what = _get_text(props, "So What Summary")
        mechanism = _get_text(props, "Mechanism")
        trajectory = _get_text(props, "Trajectory")
        actors_involved = _get_text(props, "Actors Involved")
        if title:
            feeds.append({
                "title": title,
                "so_what": so_what,
                "mechanism": mechanism,
                "trajectory": trajectory,
                "actors_involved": actors_involved,
            })
    return feeds


def check_novelty(
    article_title: str,
    article_summary: str,
    article_argument: str,
    actors: list[str],
    region_tags: list[str],
) -> dict:
    """Run novelty check against existing Intel Feeds.

    Returns dict with verdict, novelty_score, reasoning, new_elements.
    Falls back to New Signal if anything fails — never block ingestion on error.
    """
    fallback = {
        "verdict": "New Signal",
        "novelty_score": 100,
        "reasoning": "Novelty check could not be completed — defaulting to ingest.",
        "new_elements": None,
    }

    try:
        existing = fetch_existing_feeds(actors, region_tags)

        if not existing:
            return {
                "verdict": "New Signal",
                "novelty_score": 100,
                "reasoning": "No existing Intel Feed entries found for these actors or region.",
                "new_elements": "First coverage of this actor/region combination.",
            }

        existing_summary = "\n\n".join([
            f"EXISTING ENTRY: {f['title']}\n"
            f"So What: {f['so_what']}\n"
            f"Mechanism: {f['mechanism']}\n"
            f"Trajectory: {f['trajectory']}"
            for f in existing
        ])

        user_message = (
            f"INCOMING ARTICLE:\n"
            f"Title: {article_title}\n"
            f"Summary: {article_summary}\n"
            f"Core Argument: {article_argument}\n"
            f"Actors: {', '.join(actors) if actors else 'Not specified'}\n\n"
            f"EXISTING INTEL FEEDS ON SAME ACTORS/REGION:\n"
            f"{existing_summary}\n\n"
            f"Assess whether the incoming article adds new analytical value."
        )

        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=512,
            system=[{
                "type": "text",
                "text": _NOVELTY_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": user_message}],
        )

        raw = response.content[0].text.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()
        result = json.loads(cleaned)

        if result.get("verdict") not in NOVELTY_VERDICTS:
            result["verdict"] = "New Signal"

        return result

    except Exception as e:
        console.print(f"[yellow]Warning:[/yellow] Novelty check failed: {e}. Defaulting to New Signal.")
        return fallback


# --- Notion property helpers ---

def _get_title(props: dict, key: str) -> str:
    try:
        return props[key]["title"][0]["plain_text"]
    except (KeyError, IndexError):
        return ""


def _get_text(props: dict, key: str) -> str:
    try:
        parts = props[key].get("rich_text", [])
        return " ".join(p["plain_text"] for p in parts)
    except (KeyError, TypeError):
        return ""
