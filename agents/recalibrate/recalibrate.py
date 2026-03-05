"""Recalibration agent: fetch registry, run Claude calibration pass, validate, write approved changes."""

from __future__ import annotations

import datetime
import json
import re
from typing import Any

_EST = datetime.timezone(datetime.timedelta(hours=-5))

import anthropic
import requests
from notion_client import Client
from notion_client.errors import APIResponseError

from agents.recalibrate.anchors import ANCHOR_ACTORS, get_anchor_names
from config.settings import (
    ANTHROPIC_API_KEY,
    NOTION_ACTIVITY_LOG_DB_ID,
    NOTION_ACTORS_DB_ID,
    NOTION_API_KEY,
    NOTION_SCORE_SNAPSHOTS_DB_ID,
)

# Recalibration uses Opus for calibration pass; prompt caching on system prompt
CLAUDE_RECAL_MODEL = "claude-opus-4-5-20251101"
CLAUDE_RECAL_MAX_TOKENS = 4096

_NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_API_KEY}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}

_SYSTEM_PROMPT = """\
You are a senior geopolitical analyst performing a calibration pass on PowerFlow scores.

PowerFlow measures real power dynamics — the gap between claimed authority and exercised control:
- Authority Score (0–100): Actual internal control within claimed domain
- Reach Score (0–100): External influence projection beyond own borders
- PF Score = Authority × 0.6 + Reach × 0.4

You have a tiered anchor system spanning the full 0–100 range. These anchors are locked reference points that define the distribution at each level. Your job is to evaluate the full actor registry and identify scores that need adjustment for any of these reasons:

1. ANCHOR INCONSISTENCY — Actor scores higher or lower than it should relative to nearby anchors (e.g., a degraded militia scoring above Hezbollah pre-2024 baseline)
2. INTERNAL INCONSISTENCY — Reach significantly exceeds Authority for a state actor with no power projection doctrine, or vice versa in ways that don't reflect reality
3. DISTRIBUTION COMPRESSION — Multiple actors clustered at nearly identical scores where meaningful differences exist in reality
4. DRIFT — Score no longer reflects known geopolitical reality based on major events (leadership changes, military defeats, territorial losses, sanctions, etc.)

For each actor needing adjustment, provide recommended scores and a concise rationale anchored to specific reference points. Only flag actors that genuinely need adjustment — if a score is defensible, leave it.

Return ONLY valid JSON. No preamble, no markdown, no code fences.

Schema:
{
  "adjustments": [
    {
      "actor_name": "string",
      "current_authority": int,
      "current_reach": int,
      "current_pf_score": int,
      "recommended_authority": int,
      "recommended_reach": int,
      "recommended_pf_score": int,
      "calibration_rationale": "string (2-3 sentences referencing specific anchors and peers)",
      "confidence": "High | Medium | Low",
      "adjustment_reason": "Anchor Inconsistency | Internal Inconsistency | Distribution Compression | Drift"
    }
  ],
  "distribution_notes": "string — 2-3 sentence overall assessment of registry health and any systemic patterns"
}\
"""


def pf_score(authority: int, reach: int) -> int:
    """Compute PF Score from Authority and Reach. Always use this for canonical value."""
    return round(authority * 0.6 + reach * 0.4)


# ── Step 1: Pull full actor registry ─────────────────────────────────────────

def fetch_full_registry() -> list[dict[str, Any]]:
    """Fetch all actors from Actors Registry with pagination. Returns list of actor dicts with page_id, name, actor_type, authority, reach, pf_score, last_updated."""
    url = f"https://api.notion.com/v1/databases/{NOTION_ACTORS_DB_ID}/query"
    results: list[dict[str, Any]] = []
    start_cursor: str | None = None

    while True:
        payload: dict[str, Any] = {}
        if start_cursor:
            payload["start_cursor"] = start_cursor

        response = requests.post(url, headers=_NOTION_HEADERS, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()

        for page in data.get("results", []):
            props = page.get("properties", {})
            name = _extract_title(props.get("Name", {}))
            if not name:
                continue
            actor_type = (props.get("Actor Type", {}).get("select") or {}).get("name", "Non-State")
            authority = props.get("Authority Score", {}).get("number")
            reach = props.get("Reach Score", {}).get("number")
            if authority is not None and reach is not None:
                pf = pf_score(int(authority), int(reach))
            else:
                pf = None
            last_updated = None
            last_prop = props.get("Last Scored", {}) or props.get("Last Updated", {})
            date_obj = last_prop.get("date") or {}
            if date_obj:
                last_updated = date_obj.get("start")

            results.append({
                "page_id": page["id"],
                "name": name,
                "actor_type": actor_type,
                "authority": int(authority) if authority is not None else None,
                "reach": int(reach) if reach is not None else None,
                "pf_score": pf,
                "last_updated": last_updated,
            })

        if data.get("has_more") and data.get("next_cursor"):
            start_cursor = data["next_cursor"]
        else:
            break

    return results


def _extract_title(prop: dict) -> str:
    items = prop.get("title", [])
    return "".join(item.get("plain_text", "") for item in items).strip()


# ── Step 2 & 3: Build context and call Claude ───────────────────────────────────

_TIER_NUMBERS = {"Top": 1, "High": 2, "Mid-High": 3, "Mid": 4, "Mid-Low": 5, "Low": 6, "Floor": 7}


def _format_anchor_context() -> str:
    """Format tiered anchors for the prompt."""
    by_tier: dict[str, list[tuple[str, dict]]] = {}
    for name, data in ANCHOR_ACTORS.items():
        tier = data["tier"]
        by_tier.setdefault(tier, []).append((name, data))
    tier_order = ["Top", "High", "Mid-High", "Mid", "Mid-Low", "Low", "Floor"]
    lines = ["TIERED ANCHOR REFERENCE POINTS (locked — do not adjust):", ""]
    for tier in tier_order:
        if tier not in by_tier:
            continue
        num = _TIER_NUMBERS.get(tier, 0)
        lines.append(f"[Tier {num} — {tier}]")
        for name, d in by_tier[tier]:
            lines.append(f"{name}: Authority {d['authority']}, Reach {d['reach']}, PF {d['pf_score']}")
        lines.append("")
    return "\n".join(lines).strip()


def _format_registry_context(actors: list[dict[str, Any]]) -> str:
    """Format current registry for the prompt (all actors, including anchors for context)."""
    lines = ["CURRENT ACTOR REGISTRY (evaluate for calibration):"]
    for a in actors:
        auth = a.get("authority")
        reach = a.get("reach")
        pf = a.get("pf_score")
        auth_s = str(auth) if auth is not None else "—"
        reach_s = str(reach) if reach is not None else "—"
        pf_s = str(pf) if pf is not None else "—"
        lines.append(
            f"- {a['name']} | Type: {a.get('actor_type', '')} | Authority: {auth_s} | Reach: {reach_s} | PF: {pf_s}"
        )
    return "\n".join(lines)


def run_calibration_pass(actors: list[dict[str, Any]]) -> dict[str, Any]:
    """Run Claude calibration pass. Returns parsed JSON with adjustments and distribution_notes. Raises on API or parse error."""
    anchor_block = _format_anchor_context()
    registry_block = _format_registry_context(actors)
    user_msg = f"{anchor_block}\n\n{registry_block}"

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    message = client.messages.create(
        model=CLAUDE_RECAL_MODEL,
        max_tokens=CLAUDE_RECAL_MAX_TOKENS,
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
    return _parse_calibration_json(raw)


def _parse_calibration_json(raw: str) -> dict[str, Any]:
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        raise ValueError("No JSON object found in Claude response")
    return json.loads(match.group())


# ── Step 4: Validate ─────────────────────────────────────────────────────────

def validate_adjustments(
    raw_result: dict[str, Any],
    name_to_actor: dict[str, dict[str, Any]],
    anchor_names: set[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Validate calibration output: recalc PF, drop anchors, flag out-of-range. Returns (valid_adjustments, invalid_reasons)."""
    adjustments = raw_result.get("adjustments") or []
    valid: list[dict[str, Any]] = []
    invalid_reasons: list[str] = []

    for adj in adjustments:
        actor_name = (adj.get("actor_name") or "").strip()
        if not actor_name:
            invalid_reasons.append("Adjustment missing actor_name; skipped")
            continue
        if actor_name in anchor_names:
            invalid_reasons.append(f"'{actor_name}' is an anchor; dropped")
            continue

        rec_auth = adj.get("recommended_authority")
        rec_reach = adj.get("recommended_reach")
        if rec_auth is None or rec_reach is None:
            invalid_reasons.append(f"'{actor_name}': missing recommended_authority or recommended_reach")
            continue
        try:
            rec_auth = int(rec_auth)
            rec_reach = int(rec_reach)
        except (TypeError, ValueError):
            invalid_reasons.append(f"'{actor_name}': non-integer authority/reach")
            continue
        if not (0 <= rec_auth <= 100 and 0 <= rec_reach <= 100):
            invalid_reasons.append(f"'{actor_name}': recommended scores outside 0–100")
            continue

        correct_pf = pf_score(rec_auth, rec_reach)
        adj["recommended_authority"] = rec_auth
        adj["recommended_reach"] = rec_reach
        adj["recommended_pf_score"] = correct_pf

        if actor_name not in name_to_actor:
            invalid_reasons.append(f"'{actor_name}' not in current registry; skipped")
            continue

        info = name_to_actor[actor_name]
        adj["page_id"] = info["page_id"]
        adj["current_authority"] = info.get("authority")
        adj["current_reach"] = info.get("reach")
        adj["current_pf_score"] = info.get("pf_score")
        adj["actor_type"] = info.get("actor_type", "")
        valid.append(adj)

    return valid, invalid_reasons


# ── Step 6: Write approved changes ────────────────────────────────────────────

def write_approved_changes(
    approved: list[dict[str, Any]],
) -> tuple[list[str], str | None]:
    """For each approved adjustment: update Actor, create Score Snapshot. Always writes one Activity Log entry for the run (even when 0 approved).
    Returns (list of actor names that were written, activity_log_page_id or None).
    """
    client = Client(auth=NOTION_API_KEY)
    written: list[str] = []
    details: list[dict[str, Any]] = []

    for adj in approved:
        page_id = adj.get("page_id")
        actor_name = (adj.get("actor_name") or "").strip()
        rec_auth = adj["recommended_authority"]
        rec_reach = adj["recommended_reach"]
        rec_pf = adj["recommended_pf_score"]
        old_pf = adj.get("current_pf_score")
        rationale = (adj.get("calibration_rationale") or "").strip()
        reason = (adj.get("adjustment_reason") or "").strip()
        notes = f"{rationale} [{reason}]" if reason else rationale

        try:
            _update_actor_scores(client, page_id, rec_auth, rec_reach)
            _create_recalibration_snapshot(page_id, actor_name, rec_auth, rec_reach, rec_pf, notes)
            delta = (rec_pf - old_pf) if old_pf is not None else None
            details.append({
                "actor": actor_name,
                "old_pf": old_pf,
                "new_pf": rec_pf,
                "delta": round(delta, 1) if delta is not None else None,
            })
            written.append(actor_name)
        except Exception as exc:
            raise RuntimeError(f"Failed to write adjustment for {actor_name}: {exc}") from exc

    # Always write activity log for the run (including 0 adjusted)
    activity_page_id = _write_activity_log(len(approved), details)
    return written, activity_page_id


def _update_actor_scores(client: Client, page_id: str, authority: int, reach: int) -> None:
    """Update actor page with new Authority Score and Reach Score."""
    try:
        client.pages.update(
            page_id=page_id,
            properties={
                "Authority Score": {"number": authority},
                "Reach Score": {"number": reach},
            },
        )
    except APIResponseError as exc:
        raise RuntimeError(
            f"Notion API error updating actor {page_id}: {exc.status} — {exc.body}"
        ) from exc


def _create_recalibration_snapshot(
    actor_page_id: str,
    actor_name: str,
    authority: int,
    reach: int,
    pf: int,
    notes: str,
) -> None:
    """Create Score Snapshot row: Actor, Authority, Reach, PF, Snapshot Date, Source Recalibration Agent, Notes."""
    today = datetime.datetime.now(_EST).strftime("%Y-%m-%d")
    title = f"{actor_name} — Recalibration PF {pf} ({today})"
    url = "https://api.notion.com/v1/pages"
    payload: dict[str, Any] = {
        "parent": {"database_id": NOTION_SCORE_SNAPSHOTS_DB_ID},
        "properties": {
            "Title": {"title": [{"text": {"content": title[:2000]}}]},
            "Actor": {"relation": [{"id": actor_page_id}]},
            "Score": {"number": pf},
            "Snapshot Date": {"date": {"start": today}},
            "Trigger Notes": {"rich_text": [{"text": {"content": notes[:2000]}}]},
            "Agent Source": {"rich_text": [{"text": {"content": "Recalibration Agent"}}]},
            "Visibility": {"select": {"name": "Internal"}},
        },
    }
    payload["properties"]["Snapshot Type"] = {"select": {"name": "Event-Triggered"}}

    try:
        response = requests.post(url, headers=_NOTION_HEADERS, json=payload, timeout=15)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(f"Notion API error creating Score Snapshot: {exc}") from exc


def _write_activity_log(num_adjusted: int, details: list[dict[str, Any]]) -> str | None:
    """Write one Activity Log entry for the recalibration run. Returns page_id or None on failure."""
    try:
        now_utc = datetime.datetime.now(_EST).isoformat(timespec="seconds")
        action = f"Recalibration run — {num_adjusted} actors adjusted"
        details_json = json.dumps(details, indent=0)[:2000]

        url = "https://api.notion.com/v1/pages"
        full_properties = {
            "Log Title": {"title": [{"text": {"content": action}}]},
            "Timestamp": {"date": {"start": now_utc}},
            "Status": {"select": {"name": "Completed"}},
            "Visibility": {"select": {"name": "Internal"}},
            "Summary": {"rich_text": [{"text": {"content": details_json}}]},
        }
        # Add Agent ID and Action Type if schema supports them (user may add "Recalibration Agent" / "Recalibrate")
        full_properties["Agent ID"] = {"select": {"name": "Recalibration Agent"}}
        full_properties["Action Type"] = {"select": {"name": "Recalibrate"}}

        payload = {"parent": {"database_id": NOTION_ACTIVITY_LOG_DB_ID}, "properties": full_properties}
        response = requests.post(url, headers=_NOTION_HEADERS, json=payload, timeout=15)
        response.raise_for_status()
        return response.json().get("id")
    except requests.RequestException:
        # Fallback: try minimal properties in case Agent ID / Action Type options don't exist
        try:
            payload = {
                "parent": {"database_id": NOTION_ACTIVITY_LOG_DB_ID},
                "properties": {
                    "Log Title": {"title": [{"text": {"content": action}}]},
                    "Timestamp": {"date": {"start": now_utc}},
                    "Status": {"select": {"name": "Completed"}},
                    "Summary": {"rich_text": [{"text": {"content": details_json}}]},
                },
            }
            response = requests.post(url, headers=_NOTION_HEADERS, json=payload, timeout=15)
            response.raise_for_status()
            return response.json().get("id")
        except Exception:
            return None
