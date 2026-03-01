"""Claude synthesis and Notion write for the PowerFlow briefing agent.

Responsibilities:
  - generate_brief(): calls Claude Opus to synthesize a weekly intelligence brief
  - save_brief(): writes the approved brief to the Notion Briefs database
  - log_brief_activity(): records the synthesis run in the Agent Activity Log
"""

from __future__ import annotations

import datetime
from typing import Any

import anthropic
import requests

from config.settings import (
    ANTHROPIC_API_KEY,
    BRIEFS_DB_ID,
    NOTION_API_KEY,
    NOTION_ACTIVITY_LOG_DB_ID,
)

_NOTION_VERSION = "2022-06-28"
_NOTION_BASE = "https://api.notion.com/v1"
_BRIEF_MODEL = "claude-opus-4-6"
_BRIEF_MAX_TOKENS = 2500

_SYSTEM_PROMPT = """\
You are the analytical engine for PowerFlow, a geopolitical intelligence system that tracks \
the gap between claimed authority and exercised control. Your task is to synthesize recent \
system data into a concise, structured weekly intelligence brief.

The brief should read like a high-quality analyst note — not a news summary. Prioritize \
analytical insight over event description. Tell the reader what the data reveals about \
underlying power dynamics, not just what happened. Be specific and non-obvious. Avoid \
motivational language, generic framing, and restating what the reader can already see.

Output format — use these exact section headers in this order:

## THE HEADLINE
One paragraph (3-4 sentences). The single most analytically significant structural shift \
this week and why it matters beyond the immediate event. Set the frame for everything that \
follows.

## KEY MOVEMENTS
The 3-5 most consequential PF score shifts only — not all of them. Select based on \
analytical significance, not size of delta. Format each as:
**[Actor]** — Δ [delta] → [brief analytical clause explaining what the shift means, not \
just what caused it].

Skip minor or baseline-entry score changes. The reader will see the full ledger at the \
bottom.

## ANALYTICAL SYNTHESIS
2-3 paragraphs. This is the core intelligence layer. Synthesize the week's pattern: what \
do the events and score shifts, taken together, reveal about the underlying system? What is \
the second-order story that a news reader would miss? What structural dynamic has been \
confirmed, accelerated, or broken this week? Reference specific actors and events but focus \
on what they *mean* for the power landscape, not what happened.

## SCENARIOS TO WATCH
For each active scenario provided: **bold name**, probability estimate, one sentence on \
current status, one sentence on the specific trigger condition to monitor. Be concrete — \
name the actual threshold, not a generic "watch for escalation."

## SCORE LEDGER
Full list of all score changes this week in compact format. One line per actor: \
**[Actor]** Δ[delta] ([old] → [new]) — [one brief clause only]. No elaboration — this \
section is reference, not analysis.\
"""


def _format_events(events: list[dict[str, Any]]) -> str:
    if not events:
        return "  (none this period)"
    lines: list[str] = []
    for e in events:
        parts = [f"- [{e.get('event_type', 'Event')}] {e.get('name', 'Unnamed')}"]
        if e.get("date"):
            parts[0] += f" ({e['date']})"
        if e.get("pf_signal"):
            parts[0] += f" | PF Signal: {e['pf_signal']}"
        if e.get("description"):
            parts.append(f"  {e['description']}")
        lines.append("\n".join(parts))
    return "\n".join(lines)


def _format_intel_feeds(feeds: list[dict[str, Any]]) -> str:
    if not feeds:
        return "  (none this period)"
    lines: list[str] = []
    for f in feeds:
        line = f"- {f.get('name', 'Unnamed')}"
        if f.get("confidence_shift"):
            line += f" | {f['confidence_shift']}"
        if f.get("so_what_summary"):
            line += f"\n  {f['so_what_summary']}"
        lines.append(line)
    return "\n".join(lines)


def _format_score_snapshots(snapshots: list[dict[str, Any]]) -> str:
    if not snapshots:
        return "  (no material score changes this period)"
    lines: list[str] = []
    for s in snapshots:
        actor = s.get("actor") or s.get("title") or "Unknown"
        delta = s.get("score_delta")
        score = s.get("score")
        delta_str = f"{delta:+.0f}" if delta is not None else "n/a"
        score_str = f"{score:.0f}" if score is not None else "n/a"
        line = f"- **{actor}** | Score: {score_str} (Δ {delta_str})"
        if s.get("trigger_notes"):
            line += f"\n  {s['trigger_notes']}"
        lines.append(line)
    return "\n".join(lines)


def _format_scenarios(scenarios: list[dict[str, Any]]) -> str:
    if not scenarios:
        return "  (no active scenarios)"
    lines: list[str] = []
    for sc in scenarios:
        line = f"- **{sc.get('name', 'Unnamed')}**"
        if sc.get("scenario_class"):
            line += f" [{sc['scenario_class']}]"
        if sc.get("probability_estimate"):
            line += f" | p={sc['probability_estimate']}"
        if sc.get("trigger_condition"):
            line += f"\n  Trigger: {sc['trigger_condition']}"
        lines.append(line)
    return "\n".join(lines)


def generate_brief(data: dict[str, Any], priority: str) -> str:
    """Synthesize a weekly intelligence brief via Claude Opus.

    Args:
        data: The unified dict returned by fetcher.fetch_all().
        priority: The analyst's editorial priority/focus input.

    Returns:
        The raw brief text from Claude.

    Raises:
        RuntimeError: If the Anthropic API call fails.
    """
    events = data.get("events", [])
    feeds = data.get("intel_feeds", [])
    snapshots = data.get("score_snapshots", [])
    scenarios = data.get("active_scenarios", [])
    date_range = data.get("date_range", "")

    user_prompt = f"""\
EDITORIAL PRIORITY: {priority or "No specific priority — use your analytical judgment."}

RECENT DATA:

EVENTS ({len(events)} this week):
{_format_events(events)}

INTELLIGENCE FEEDS ({len(feeds)} this week):
{_format_intel_feeds(feeds)}

SCORE MOVERS ({len(snapshots)} this week):
{_format_score_snapshots(snapshots)}

ACTIVE SCENARIOS:
{_format_scenarios(scenarios)}

DATE RANGE: {date_range}

Generate the PowerFlow Weekly Brief now."""

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    try:
        message = client.messages.create(
            model=_BRIEF_MODEL,
            max_tokens=_BRIEF_MAX_TOKENS,
            system=[
                {
                    "type": "text",
                    "text": _SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_prompt}],
        )
    except anthropic.APIError as exc:
        raise RuntimeError(f"Anthropic API error during brief synthesis: {exc}") from exc

    return message.content[0].text.strip()


# ── Notion write helpers ───────────────────────────────────────────────────────

def _notion_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Content-Type": "application/json",
        "Notion-Version": _NOTION_VERSION,
    }


def _title(text: str) -> dict:
    return {"title": [{"text": {"content": text[:2000]}}]}


def _rich_text(text: str) -> dict:
    chunks = [text[i:i + 2000] for i in range(0, max(len(text), 1), 2000)]
    return {"rich_text": [{"text": {"content": chunk}} for chunk in chunks]}


def _select(value: str) -> dict:
    return {"select": {"name": value}}


def _date_prop(iso_date: str) -> dict:
    return {"date": {"start": iso_date}}


def _brief_text_to_blocks(text: str) -> list[dict[str, Any]]:
    """Convert markdown brief text into Notion block objects for the page body.

    Handles ## headings, **bold** inline, and paragraph text. Each line
    becomes a paragraph or heading_2 block. Blank lines are skipped.
    """
    blocks: list[dict[str, Any]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        if stripped.startswith("## "):
            heading = stripped[3:].strip()
            blocks.append({
                "object": "block",
                "type": "heading_2",
                "heading_2": {
                    "rich_text": [{"type": "text", "text": {"content": heading}}]
                },
            })
        else:
            # Parse inline bold (**text**) into annotated rich_text segments
            rich_text = _parse_inline_bold(stripped)
            blocks.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": rich_text},
            })

    return blocks


def _parse_inline_bold(text: str) -> list[dict[str, Any]]:
    """Split text on **...** markers and return Notion rich_text segments."""
    import re
    parts = re.split(r"(\*\*[^*]+\*\*)", text)
    segments: list[dict[str, Any]] = []
    for part in parts:
        if part.startswith("**") and part.endswith("**"):
            segments.append({
                "type": "text",
                "text": {"content": part[2:-2]},
                "annotations": {"bold": True},
            })
        elif part:
            segments.append({"type": "text", "text": {"content": part}})
    return segments or [{"type": "text", "text": {"content": text}}]


def save_brief(
    brief_text: str,
    date_range: str,
    priority: str,
    date_range_start: str,
    date_range_end: str = "",
) -> tuple[str, str]:
    """Write an approved brief to the Notion Briefs database.

    Args:
        brief_text: The full synthesized brief markdown.
        date_range: Human-readable label e.g. "Feb 22 – Feb 28, 2026".
        priority: The editorial priority text entered by the analyst.
        date_range_start: ISO date string for the start of the brief window.
        date_range_end: ISO date string for the end of the brief window (optional).

    Returns:
        (page_id, page_url) tuple.

    Raises:
        RuntimeError: If BRIEFS_DB_ID is not configured or the API call fails.
    """
    if not BRIEFS_DB_ID:
        raise RuntimeError(
            "BRIEFS_DB_ID is not configured in settings.py. "
            "Create the Briefs database in Notion and set the ID."
        )

    title = f"Weekly Brief — {date_range}"

    properties: dict[str, Any] = {
        "Title": _title(title),
        "Brief Type": _select("Weekly"),
        # "Generated By" is a select, not rich_text
        "Generated By": _select("Agent-F: Synthesis"),
        "Date Range": _rich_text(date_range),
        "Editorial Priority": _rich_text(priority),
        "Status": _select("Draft"),
        "Visibility": _select("Internal"),
    }

    if date_range_start:
        properties["Period Start"] = _date_prop(date_range_start)
    if date_range_end:
        properties["Period End"] = _date_prop(date_range_end)

    blocks = _brief_text_to_blocks(brief_text)

    url = f"{_NOTION_BASE}/pages"
    payload: dict[str, Any] = {
        "parent": {"database_id": BRIEFS_DB_ID},
        "properties": properties,
        "children": blocks,
    }

    import json
    print("[save_brief] Notion request payload:")
    print(json.dumps(payload, indent=2, default=str))

    try:
        response = requests.post(url, headers=_notion_headers(), json=payload, timeout=30)
        if not response.ok:
            print(f"[save_brief] Notion API error {response.status_code}: {response.text}")
        response.raise_for_status()
    except requests.exceptions.RequestException as exc:
        raise RuntimeError(f"Notion API error writing brief: {exc}") from exc

    data = response.json()
    page_id: str = data["id"]
    page_url: str = data.get("url", f"https://notion.so/{page_id.replace('-', '')}")
    return page_id, page_url


def log_brief_activity(status: str = "Completed", notes: str = "") -> None:
    """Log the synthesis run to the Agent Activity Log. Never raises."""
    if not NOTION_ACTIVITY_LOG_DB_ID:
        return

    try:
        now_utc = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
        properties: dict[str, Any] = {
            "Log Title": _title("PowerFlow Weekly Brief — Synthesis"),
            "Agent ID": _select("Agent-F: Synthesis"),
            "Action Type": _select("Synthesis Write"),
            "Timestamp": {"date": {"start": now_utc}},
            "Status": _select(status),
            "Visibility": _select("Internal"),
        }
        if notes:
            properties["Notes"] = _rich_text(notes)

        url = f"{_NOTION_BASE}/pages"
        payload = {
            "parent": {"database_id": NOTION_ACTIVITY_LOG_DB_ID},
            "properties": properties,
        }
        requests.post(url, headers=_notion_headers(), json=payload, timeout=15)
    except Exception:
        pass
