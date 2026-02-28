"""Core scoring logic for the PowerFlow Score Agent.

Computes Authority Score and Reach Score for geopolitical actors using Claude,
then writes results back to the Actors Registry in Notion.
"""

import datetime
import json
import re

import anthropic
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
   specifically for THIS actor (not generically). Widens = actor losing control/influence. \
   Narrows = actor consolidating. Recent events (last 6 months) carry more weight.
3. Apply case study context if available: treat as long-run structural anchor, \
   can shift baseline by up to 15 points either direction on either sub-score.
4. Produce a final score and a reasoning note.

SCORE RANGES:

Authority Score:
- 80-100: Near-total effective control within claimed domain. Challenges are minor or suppressed.
- 60-79: Strong but imperfect control. Meaningful opposition or gaps exist but don't threaten core grip.
- 40-59: Contested control. Rival power structures, significant ungoverned areas, or dependency on external support.
- 20-39: Fragmented. Nominal authority only in significant portions of claimed domain.
- 0-19: Failed or non-existent internal control. Exists as a label more than a functioning structure.

Reach Score:
- 80-100: Shapes outcomes in multiple external theaters. Other actors must account for this one.
- 60-79: Significant regional influence. Can shift outcomes in specific external arenas.
- 40-59: Moderate reach. Influence felt but not decisive externally.
- 20-39: Mostly reactive. Limited ability to shape external outcomes.
- 0-19: No meaningful external reach. Domestically confined or irrelevant to others.

REASONING NOTE: Write 2-3 sentences that explain the score with reference to specific \
events or structural conditions. Do not be generic. Name the dynamics. This note will \
appear on the public-facing dashboard — write it for an informed layperson, not an analyst. \
Example of good reasoning: "Pakistan's Authority Score reflects deepening fragmentation \
along the Afghan border following February 2026 airstrikes that failed to dislodge TTP \
from Pakistani territory it effectively governs. Its Reach Score remains moderate — \
nuclear deterrence and regional positioning give it leverage, but the loss of Taliban \
patronage removes a key instrument of external influence."

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

    1. Fetches actor context from Notion.
    2. Builds a Claude prompt.
    3. Parses and validates the JSON response.
    4. Writes scores back to Notion.

    Returns a result dict with actor_name, scores, reasoning, success, error.
    Raises RuntimeError on unrecoverable failure.
    """
    context = notion_reader.fetch_actor_context(actor_page_id)
    actor_name = context["name"]
    actor_type = context["actor_type"]

    auth_baseline = _AUTHORITY_BASELINES.get(actor_type, _DEFAULT_BASELINE)
    reach_baseline = _REACH_BASELINES.get(actor_type, _DEFAULT_BASELINE)

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

    return {
        "actor_name": actor_name,
        "actor_page_id": actor_page_id,
        "authority_score": scores["authority_score"],
        "reach_score": scores["reach_score"],
        "pf_score": pf_score,
        "reasoning": scores["reasoning"],
        "success": True,
        "error": None,
    }


def score_actors(actor_page_ids: list[str]) -> list[dict]:
    """Score a list of actors, logging progress with rich.

    Does not stop on individual failures — catches exceptions per actor,
    logs the error, and continues to the next.

    Returns a list of result dicts (see score_actor for schema).
    """
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


# ── Internal helpers ──────────────────────────────────────────────────────────

def _build_user_message(context: dict, auth_baseline: int, reach_baseline: int) -> str:
    actor_name = context["name"]
    actor_type = context["actor_type"]
    linked_events: list[dict] = context["linked_events"]
    linked_case_studies: list[dict] = context["linked_case_studies"]

    events_lines = []
    for ev in linked_events:
        date_str = ev.get("date") or "unknown date"
        ev_name = ev.get("event_name", "Unnamed event")
        signal = ev.get("pf_signal", "")
        desc = ev.get("description", "")
        events_lines.append(f"- [{date_str}] {ev_name} | PF Signal: {signal} | {desc}")

    cs_lines = []
    for cs in linked_case_studies:
        title = cs.get("title", "Untitled")
        summary = cs.get("summary", "")
        cs_lines.append(f"- {title}: {summary}")

    events_block = "\n".join(events_lines) if events_lines else "(none)"
    cs_block = "\n".join(cs_lines) if cs_lines else "(none)"

    return (
        f"ACTOR: {actor_name}\n"
        f"TYPE: {actor_type}\n"
        f"AUTHORITY BASELINE: {auth_baseline}\n"
        f"REACH BASELINE: {reach_baseline}\n"
        f"\n"
        f"LINKED EVENTS ({len(linked_events)}):\n"
        f"{events_block}\n"
        f"\n"
        f"LINKED CASE STUDIES ({len(linked_case_studies)}):\n"
        f"{cs_block}\n"
        f"\n"
        "Score this actor. Apply the framework. Return only the JSON object."
    )


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
