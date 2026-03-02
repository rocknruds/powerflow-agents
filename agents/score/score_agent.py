"""Core scoring logic for the PowerFlow Score Agent.

Computes Authority Score and Reach Score for geopolitical actors using Claude,
then writes results back to the Actors Registry in Notion.

Relationship-aware: traverses Patron State and proxy actor relations so that
scores reflect the dependency network, not just isolated event signals.
"""

import datetime
import json
import re

import anthropic
import requests
from notion_client import Client
from notion_client.errors import APIResponseError
from rich.console import Console

from agents.score import notion_reader
from config.settings import (
    ANTHROPIC_API_KEY,
    CLAUDE_SCORE_MAX_TOKENS,
    CLAUDE_SCORE_MODEL,
    NOTION_API_KEY,
)

console = Console()

_SCORE_SNAPSHOTS_DB_ID = "e96696510cac4435a52e89be9fb6a969"

# ── Baselines by actor type ───────────────────────────────────────────────────

_AUTHORITY_BASELINES = {
    "State": 50,
    "Hybrid": 35,
    "Non-State": 20,
    "IGO": 10,
    "Individual": 15,
}

_REACH_BASELINES = {
    "State": 35,
    "Hybrid": 25,
    "Non-State": 15,
    "IGO": 45,
    "Individual": 20,
}

_DEFAULT_BASELINE = 25

# ── Prompts ───────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are a senior geopolitical analyst for PowerFlow, a system that scores how power \
actually moves through the world. Your task is to compute two scores for a specific \
geopolitical actor based on available intelligence.

POWERFLOW SCORE FRAMEWORK:

Authority Score (0-100): How much real internal control does this actor exercise \
within its claimed territory or domain? Measures consolidated grip, not formal claims.

Reach Score (0-100): How much external influence does this actor project beyond its \
own borders? Measures ability to shape outcomes in other actors' arenas.

PF Score = Authority * 0.6 + Reach * 0.4 (computed automatically — do not return this)

SCORING APPROACH:
1. Start from the baseline for this actor's type (provided in input)
2. Apply event signals: for each linked event, reason about what the PF Signal means \
   specifically for THIS actor. Widens = actor losing control/influence. \
   Narrows = actor consolidating. Recent events carry more weight.
3. Apply relationship context (critical — this is where most analysts go wrong):

   PATRON STATE: If this actor has a patron, the patron's current PF Score is a \
   structural ceiling on the actor's Reach. An agent cannot project influence beyond \
   what its patron enables. If the patron has collapsed, degraded, or been destroyed, \
   this must reduce the actor's Reach Score significantly — even if no direct event \
   links the two. The relationship IS the mechanism.

   PROXY NETWORK: If this actor sponsors proxy actors, their health reflects the \
   patron's real reach. A patron whose proxies are all degraded or destroyed has lost \
   its primary mechanism of external influence, regardless of its domestic authority.

4. Apply case study context if available: treat as long-run structural anchor, \
   can shift baseline by up to 15 points either direction on either sub-score.

SCORE RANGES:

Authority Score:
- 80-100: Near-total effective control. Challenges are minor or suppressed.
- 60-79: Strong but imperfect control. Meaningful opposition exists but doesn't threaten core grip.
- 40-59: Contested. Rival power structures, significant ungoverned areas, or external dependency.
- 20-39: Fragmented. Nominal authority only across significant portions of claimed domain.
- 0-19: Failed or non-existent. Exists as a label more than a functioning structure.

Reach Score:
- 80-100: Shapes outcomes in multiple external theaters. Others must account for this actor.
- 60-79: Significant regional influence. Can shift outcomes in specific external arenas.
- 40-59: Moderate reach. Influence felt but not decisive externally.
- 20-39: Mostly reactive. Limited ability to shape external outcomes.
- 0-19: No meaningful external reach. Domestically confined or irrelevant to others.

REASONING NOTE: 2-3 sentences explaining the score with reference to specific events \
or structural conditions. Name the dynamics. Reference relationship dependencies explicitly \
when they drive the score. Write for an informed layperson — not an analyst.
Example: "Hezbollah's Reach Score has collapsed following Iran's military dismantlement \
in February 2026 — the IRGC's destruction removed the financial, logistical, and \
intelligence architecture that made Hezbollah's external operations possible. Its \
Authority Score is more resilient: the parallel governance structures in southern Lebanon \
predate IRGC patronage and won't evaporate overnight, but without resupply, degradation \
is inevitable."

CRITICAL: Return ONLY a valid JSON object. No markdown, no commentary.
{
  "authority_score": <integer 0-100>,
  "reach_score": <integer 0-100>,
  "reasoning": "<2-3 sentences for an informed layperson>"
}\
"""

_STRICT_SUFFIX = (
    "\n\nCRITICAL: Return ONLY the JSON object. "
    "No markdown fences, no commentary, no explanation. "
    "The response must start with { and end with }."
)


# ── Public API ────────────────────────────────────────────────────────────────

def score_actor(actor_page_id: str) -> dict:
    """Orchestrate the full scoring flow for one actor.

    1. Fetches actor context including relationship web from Notion.
    2. Builds a relationship-aware Claude prompt.
    3. Parses and validates the JSON response.
    4. Writes scores back to Notion.
    5. Writes a score snapshot.

    Returns a result dict with actor_name, scores, reasoning, success, error.
    """
    context = notion_reader.fetch_actor_context(actor_page_id)
    actor_name = context["name"]
    actor_type = context["actor_type"]

    auth_baseline = _AUTHORITY_BASELINES.get(actor_type, _DEFAULT_BASELINE)
    reach_baseline = _REACH_BASELINES.get(actor_type, _DEFAULT_BASELINE)

    old_pf_score = _fetch_existing_pf_score(actor_page_id)

    user_msg = _build_user_message(context, auth_baseline, reach_baseline)

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    raw = _call_claude(client, user_msg, strict=False)

    try:
        scores = _parse_json(raw)
    except ValueError:
        console.print(
            f"[yellow]Warning:[/yellow] Claude returned malformed JSON for {actor_name}. "
            "Retrying with stricter prompt..."
        )
        raw = _call_claude(client, user_msg, strict=True)
        try:
            scores = _parse_json(raw)
        except ValueError as exc:
            raise RuntimeError(
                f"Claude returned malformed JSON on both attempts for {actor_name}.\n"
                f"Raw response:\n{raw}"
            ) from exc

    _validate_scores(scores)
    _write_scores_to_notion(actor_page_id, scores)

    pf_score = scores["authority_score"] * 0.6 + scores["reach_score"] * 0.4
    _write_score_snapshot(actor_page_id, actor_name, pf_score, old_pf_score, scores["reasoning"])

    return {
        "actor_name": actor_name,
        "actor_page_id": actor_page_id,
        "authority_score": scores["authority_score"],
        "reach_score": scores["reach_score"],
        "pf_score": pf_score,
        "old_pf_score": old_pf_score,
        "reasoning": scores["reasoning"],
        "success": True,
        "error": None,
    }


def score_actors(actor_page_ids: list[str]) -> list[dict]:
    """Score a list of actors. Does not stop on individual failures."""
    results = []
    total = len(actor_page_ids)

    for i, actor_page_id in enumerate(actor_page_ids, 1):
        console.print(f"[dim]Scoring actor {i}/{total} ({actor_page_id})...[/dim]")
        try:
            result = score_actor(actor_page_id)
            results.append(result)
        except Exception as exc:
            console.print(
                f"[yellow]Warning:[/yellow] Failed to score actor {actor_page_id}: {exc}"
            )
            results.append({
                "actor_name": actor_page_id,
                "actor_page_id": actor_page_id,
                "authority_score": None,
                "reach_score": None,
                "pf_score": None,
                "reasoning": None,
                "success": False,
                "error": str(exc),
            })

    return results


# ── Prompt builder ────────────────────────────────────────────────────────────

def _build_user_message(context: dict, auth_baseline: int, reach_baseline: int) -> str:
    actor_name = context["name"]
    actor_type = context["actor_type"]
    proxy_depth = context.get("proxy_depth", "None")
    linked_events = context["linked_events"]
    linked_case_studies = context["linked_case_studies"]
    patron_context = context.get("patron_context")
    proxy_actors = context.get("proxy_actors", [])

    # Events block
    events_lines = []
    for ev in linked_events:
        date_str = ev.get("date") or "unknown date"
        ev_name = ev.get("event_name", "Unnamed event")
        signal = ev.get("pf_signal", "")
        desc = ev.get("description", "")
        events_lines.append(f"- [{date_str}] {ev_name} | PF Signal: {signal} | {desc}")
    events_block = "\n".join(events_lines) if events_lines else "(none)"

    # Case studies block
    cs_lines = []
    for cs in linked_case_studies:
        title = cs.get("title", "Untitled")
        summary = cs.get("summary", "")
        cs_lines.append(f"- {title}: {summary}")
    cs_block = "\n".join(cs_lines) if cs_lines else "(none)"

    # Patron block — this is the key relationship context
    if patron_context:
        p = patron_context
        pf_str = f"{p['pf_score']:.0f}" if p["pf_score"] is not None else "unscored"
        auth_str = f"{p['authority_score']}" if p["authority_score"] is not None else "?"
        reach_str = f"{p["reach_score"]}" if p["reach_score"] is not None else "?"
        patron_block = (
            f"Patron: {p['name']} | Status: {p['status']} | "
            f"Authority: {auth_str} | Reach: {reach_str} | PF Score: {pf_str}\n"
            f"Patron reasoning: {p['score_reasoning'] or 'No reasoning recorded.'}"
        )
    else:
        patron_block = "(no patron — autonomous or patron not set in registry)"

    # Proxy network block
    if proxy_actors:
        proxy_lines = []
        for px in proxy_actors:
            pf_str = f"{px['pf_score']:.0f}" if px["pf_score"] is not None else "unscored"
            proxy_lines.append(
                f"- {px['name']} | Depth: {px['proxy_depth']} | Status: {px['status']} | PF: {pf_str}"
            )
        proxy_block = "\n".join(proxy_lines)
    else:
        proxy_block = "(no proxy actors found in registry)"

    return (
        f"ACTOR: {actor_name}\n"
        f"TYPE: {actor_type}\n"
        f"PROXY DEPTH: {proxy_depth}\n"
        f"AUTHORITY BASELINE: {auth_baseline}\n"
        f"REACH BASELINE: {reach_baseline}\n"
        f"\n"
        f"PATRON STATE CONTEXT:\n"
        f"{patron_block}\n"
        f"\n"
        f"PROXY NETWORK (actors this entity sponsors):\n"
        f"{proxy_block}\n"
        f"\n"
        f"LINKED EVENTS ({len(linked_events)}):\n"
        f"{events_block}\n"
        f"\n"
        f"LINKED CASE STUDIES ({len(linked_case_studies)}):\n"
        f"{cs_block}\n"
        f"\n"
        "Score this actor. The relationship context above is as important as the events. "
        "A patron's collapse must propagate to the agent's Reach Score. "
        "A proxy network's degradation must reduce the patron's Reach Score. "
        "Return only the JSON object."
    )


# ── Internal helpers ──────────────────────────────────────────────────────────

def _fetch_existing_pf_score(actor_page_id: str) -> float | None:
    """Return the current PF Score for an actor page, or None if unavailable."""
    try:
        client = Client(auth=NOTION_API_KEY)
        page = client.pages.retrieve(page_id=actor_page_id)
        props = page.get("properties", {})
        authority = props.get("Authority Score", {}).get("number")
        reach = props.get("Reach Score", {}).get("number")
        if authority is None or reach is None:
            return None
        return authority * 0.6 + reach * 0.4
    except Exception:
        return None


def _write_score_snapshot(
    actor_page_id: str,
    actor_name: str,
    new_pf_score: float,
    old_pf_score: float | None,
    reasoning: str,
) -> None:
    """Write a Score Snapshot record to Notion. Never raises."""
    try:
        delta = (new_pf_score - old_pf_score) if old_pf_score is not None else None
        if delta == 0.0:
            return

        today = datetime.date.today().isoformat()
        title = f"{actor_name} — PF {new_pf_score:.0f} ({today})"

        url = "https://api.notion.com/v1/pages"
        headers = {
            "Authorization": f"Bearer {NOTION_API_KEY}",
            "Content-Type": "application/json",
            "Notion-Version": "2022-06-28",
        }
        payload = {
            "parent": {"database_id": _SCORE_SNAPSHOTS_DB_ID},
            "properties": {
                "Title": {"title": [{"text": {"content": title}}]},
                "Actor": {"relation": [{"id": actor_page_id}]},
                "Score": {"number": round(new_pf_score, 1)},
                "Score Delta": {"number": round(delta, 1) if delta is not None else 0},
                "Snapshot Type": {"select": {"name": "Event-Triggered"}},
                "Snapshot Date": {"date": {"start": today}},
                "Trigger Notes": {"rich_text": [{"text": {"content": reasoning[:2000]}}]},
                "Agent Source": {"rich_text": [{"text": {"content": "Agent-S: Score"}}]},
                "Visibility": {"select": {"name": "Internal"}},
            },
        }
        response = requests.post(url, headers=headers, json=payload, timeout=15)
        response.raise_for_status()
    except Exception as exc:
        console.print(f"[yellow]Warning:[/yellow] Failed to write Score Snapshot for {actor_name}: {exc}")


def _call_claude(client: anthropic.Anthropic, user_msg: str, strict: bool) -> str:
    system_text = _SYSTEM_PROMPT + (_STRICT_SUFFIX if strict else "")
    message = client.messages.create(
        model=CLAUDE_SCORE_MODEL,
        max_tokens=CLAUDE_SCORE_MAX_TOKENS,
        system=[
            {
                "type": "text",
                "text": system_text,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_msg}],
    )
    return message.content[0].text.strip()


def _parse_json(raw: str) -> dict:
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        raise ValueError("No JSON object found in response")
    return json.loads(match.group())


def _validate_scores(scores: dict) -> None:
    for field in ("authority_score", "reach_score"):
        val = scores.get(field)
        if not isinstance(val, int) or not (0 <= val <= 100):
            raise ValueError(f"Invalid {field}: {val!r} — must be an integer 0–100")
    if "reasoning" not in scores or not isinstance(scores["reasoning"], str):
        raise ValueError("Missing or invalid 'reasoning' field in Claude response")


def _write_scores_to_notion(actor_page_id: str, scores: dict) -> None:
    """Update the actor page with scores, reasoning, and a Last Scored timestamp."""
    client = Client(auth=NOTION_API_KEY)
    try:
        client.pages.update(
            page_id=actor_page_id,
            properties={
                "Authority Score": {"number": scores["authority_score"]},
                "Reach Score": {"number": scores["reach_score"]},
                "Score Reasoning": _rich_text(scores["reasoning"]),
                "Last Scored": {"date": {"start": datetime.date.today().isoformat()}},
            },
        )
    except APIResponseError as exc:
        raise RuntimeError(
            f"Notion API error writing scores for actor {actor_page_id}: {exc.status} — {exc.body}"
        ) from exc


def _rich_text(text: str) -> dict:
    chunks = [text[i:i + 2000] for i in range(0, max(len(text), 1), 2000)]
    return {"rich_text": [{"text": {"content": chunk}} for chunk in chunks]}
