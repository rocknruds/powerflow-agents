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

from agents.recalibrate.anchors import ANCHOR_ACTORS
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

POWERFLOW SCORE FRAMEWORK

Authority Score (0-100): How much real internal control does this actor exercise \
within its claimed territory or domain? Measures consolidated grip, not formal claims.

Reach Score (0-100): How much external influence does this actor project beyond its \
own borders? Measures ability to shape outcomes in other actors' arenas.

PF Score = Authority x 0.6 + Reach x 0.4 — computed automatically, do not return it.

---

CALIBRATION: ANCHOR REFERENCE TABLE

These are locked reference points that define the scoring distribution. Before finalizing \
your scores, identify the two nearest anchors (one above, one below) and confirm your \
proposed scores fall correctly between them. If your score would place a degraded militia \
above Hezbollah post-Oct 7, or a weak state above Germany, you have a calibration error.

Tier 1 — Top (80-90)
  United States: Authority 85, Reach 88, PF 86
  China (CCP): Authority 82, Reach 75, PF 79

Tier 2 — High (65-78)
  Russia: Authority 74, Reach 68, PF 71
  United Kingdom: Authority 78, Reach 65, PF 73
  France: Authority 76, Reach 63, PF 71
  Germany: Authority 79, Reach 58, PF 72

Tier 3 — Mid-High (52-65)
  Israel: Authority 72, Reach 68, PF 70
  Turkey: Authority 65, Reach 58, PF 62
  India: Authority 68, Reach 52, PF 62

Tier 4 — Mid (38-52)
  Saudi Arabia: Authority 58, Reach 52, PF 56
  Iran (2023 pre-Epic Fury baseline): Authority 52, Reach 48, PF 50

Tier 5 — Mid-Low (28-38)
  Hezbollah (pre-2024 baseline): Authority 48, Reach 42, PF 46

Tier 6 — Low (12-22)
  Hamas (post-Oct 7): Authority 18, Reach 12, PF 16

Tier 7 — Floor (3-10)
  Yemen (Houthi-controlled): Authority 12, Reach 8, PF 10

---

CALIBRATION: PEER REGISTRY CONTEXT

The input includes a set of currently scored peer actors of the same type from the live \
registry. Use these as a local calibration frame. Your score must make sense relative to \
both the global anchors above AND these peers. If a peer score seems wrong to you, note \
it mentally but do not blindly converge — your job is to score this actor correctly, not \
to match peers uncritically.

---

SCORING APPROACH

Step 1 — Anchor check. Find the two nearest anchors and confirm your scores would fall \
between them correctly.

Step 2 — Apply event signals. For each linked event, reason about what the PF Signal \
means specifically for THIS actor. Widens = actor losing control or influence. \
Narrows = actor consolidating. Recent events carry more weight than older ones.

Step 3 — Apply relationship context. This is where most analysts go wrong.

  PATRON STATE — structural ceiling rule:
  The patron's current PF Score is a structural ceiling on this actor's Reach Score. \
  An agent cannot project influence beyond what its patron enables. The input will \
  explicitly state the ceiling value — do not exceed it unless there is specific \
  evidence of independent operational capacity that predates or survives the patron \
  relationship. If the patron has been destroyed or severely degraded, propagate that \
  collapse aggressively into the actor's Reach Score even if no direct event links them. \
  The relationship is the mechanism.

  PROXY NETWORK:
  If this actor sponsors proxy actors, their health reflects the patron's real reach. \
  A patron whose proxies are all degraded or destroyed has lost its primary mechanism \
  of external influence regardless of domestic authority. Proxy network collapse should \
  reduce Reach Score materially.

Step 4 — Apply case study context if available. Treat as a long-run structural anchor; \
can shift baseline by up to 15 points either direction on either sub-score.

---

SCORE RANGES

Authority:
  80-100  Near-total effective control. Challenges are minor or suppressed.
  60-79   Strong but imperfect. Meaningful opposition exists but doesn't threaten core grip.
  40-59   Contested. Rival power structures, significant ungoverned areas, or external dependency.
  20-39   Fragmented. Nominal authority only across significant portions of claimed domain.
  0-19    Failed or non-existent. Exists as a label more than a functioning structure.

Reach:
  80-100  Shapes outcomes in multiple external theaters. Others must account for this actor.
  60-79   Significant regional influence. Can shift outcomes in specific external arenas.
  40-59   Moderate reach. Influence felt but not decisive externally.
  20-39   Mostly reactive. Limited ability to shape external outcomes.
  0-19    No meaningful external reach. Domestically confined or irrelevant to others.

---

REASONING

2-3 sentences. Name the dynamics explicitly. Reference specific events, anchor comparisons, \
and relationship dependencies when they drive the score. Reference peers if your score \
diverges meaningfully from them. Write for an informed layperson.

Example: "Hezbollah's Reach Score has collapsed following Iran's military dismantlement \
in February 2026 — the IRGC's destruction removed the financial, logistical, and intelligence \
architecture that made Hezbollah's external operations possible. Scored below Hamas post-Oct 7 \
on Reach, above on Authority — the parallel governance structures in southern Lebanon predate \
IRGC patronage and remain functional. Calibrated against Yemen floor (PF 10) and \
pre-degradation Hezbollah baseline (PF 46)."

---

CRITICAL: Return ONLY a valid JSON object. No markdown, no commentary, no explanation.

{
  "authority_score": <integer 0-100>,
  "reach_score": <integer 0-100>,
  "reasoning": "<2-3 sentences>"
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
    2. Fetches peer actors of the same type for local calibration context.
    3. Builds anchor+peer-aware Claude prompt.
    4. Parses and validates the JSON response.
    5. Enforces patron ceiling programmatically as a hard cap.
    6. Writes scores back to Notion.
    7. Writes a score snapshot.

    Returns a result dict with actor_name, scores, reasoning, success, error.
    """
    context = notion_reader.fetch_actor_context(actor_page_id)
    actor_name = context["name"]
    actor_type = context["actor_type"]

    auth_baseline = _AUTHORITY_BASELINES.get(actor_type, _DEFAULT_BASELINE)
    reach_baseline = _REACH_BASELINES.get(actor_type, _DEFAULT_BASELINE)

    old_pf_score = _fetch_existing_pf_score(actor_page_id)

    peers = notion_reader.fetch_peer_actors(actor_page_id, actor_type, limit=5)

    user_msg = _build_user_message(context, auth_baseline, reach_baseline, peers)

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

    # Hard patron ceiling enforcement.
    # The prompt already explains the rationale; this catches cases where the model
    # doesn't enforce it strictly enough. Ceiling is floor(patron_pf) — conservative.
    ceiling_applied = False
    patron_context = context.get("patron_context")
    if patron_context and patron_context.get("pf_score") is not None:
        ceiling = int(patron_context["pf_score"])
        if scores["reach_score"] > ceiling:
            original_reach = scores["reach_score"]
            scores["reach_score"] = ceiling
            scores["reasoning"] += (
                f" [Reach capped at {ceiling} — patron '{patron_context['name']}' "
                f"PF ceiling applied; model proposed {original_reach}.]"
            )
            ceiling_applied = True
            console.print(
                f"[yellow]Ceiling applied:[/yellow] {actor_name} Reach "
                f"{original_reach} -> {ceiling} "
                f"(patron '{patron_context['name']}' PF = {ceiling})"
            )

    _write_scores_to_notion(actor_page_id, scores)

    pf_score = scores["authority_score"] * 0.6 + scores["reach_score"] * 0.4
    _write_score_snapshot(
        actor_page_id, actor_name, pf_score, old_pf_score, scores["reasoning"]
    )

    return {
        "actor_name": actor_name,
        "actor_page_id": actor_page_id,
        "authority_score": scores["authority_score"],
        "reach_score": scores["reach_score"],
        "pf_score": pf_score,
        "old_pf_score": old_pf_score,
        "reasoning": scores["reasoning"],
        "ceiling_applied": ceiling_applied,
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

def _build_user_message(
    context: dict,
    auth_baseline: int,
    reach_baseline: int,
    peers: list[dict],
) -> str:
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
        events_lines.append(
            f"- [{date_str}] {ev_name} | PF Signal: {signal} | {desc}"
        )
    events_block = "\n".join(events_lines) if events_lines else "(none)"

    # Case studies block
    cs_lines = []
    for cs in linked_case_studies:
        cs_lines.append(f"- {cs.get('title', 'Untitled')}: {cs.get('summary', '')}")
    cs_block = "\n".join(cs_lines) if cs_lines else "(none)"

    # Patron block — includes explicit ceiling value
    if patron_context:
        p = patron_context
        pf_str = f"{p['pf_score']:.0f}" if p["pf_score"] is not None else "unscored"
        auth_str = str(p["authority_score"]) if p["authority_score"] is not None else "?"
        reach_str = str(p["reach_score"]) if p["reach_score"] is not None else "?"
        ceiling_note = ""
        if p["pf_score"] is not None:
            ceiling_note = (
                f"\n  CEILING: This actor's Reach Score must not exceed {int(p['pf_score'])} "
                f"(patron PF Score) unless there is specific evidence of independent operational "
                f"capacity that predates or survives the patron relationship."
            )
        patron_block = (
            f"Patron: {p['name']} | Status: {p['status']} | "
            f"Authority: {auth_str} | Reach: {reach_str} | PF: {pf_str}\n"
            f"Patron reasoning: {p['score_reasoning'] or 'No reasoning recorded.'}"
            f"{ceiling_note}"
        )
    else:
        patron_block = "(no patron — autonomous or patron not set in registry)"

    # Proxy network block
    if proxy_actors:
        proxy_lines = []
        for px in proxy_actors:
            pf_str = f"{px['pf_score']:.0f}" if px["pf_score"] is not None else "unscored"
            proxy_lines.append(
                f"- {px['name']} | Depth: {px['proxy_depth']} | "
                f"Status: {px['status']} | PF: {pf_str}"
            )
        proxy_block = "\n".join(proxy_lines)
    else:
        proxy_block = "(none)"

    # Peer calibration block
    if peers:
        peer_lines = []
        for p in peers:
            line = (
                f"- {p['name']} | Authority: {p['authority']} | "
                f"Reach: {p['reach']} | PF: {p['pf_score']}"
            )
            if p.get("reasoning_snippet"):
                line += f' | "{p["reasoning_snippet"]}..."'
            peer_lines.append(line)
        peers_block = "\n".join(peer_lines)
    else:
        peers_block = "(no scored peers of this type in registry yet)"

    return (
        f"ACTOR: {actor_name}\n"
        f"TYPE: {actor_type}\n"
        f"PROXY DEPTH: {proxy_depth}\n"
        f"AUTHORITY BASELINE FOR THIS TYPE: {auth_baseline}\n"
        f"REACH BASELINE FOR THIS TYPE: {reach_baseline}\n"
        f"\n"
        f"PATRON STATE CONTEXT:\n"
        f"{patron_block}\n"
        f"\n"
        f"PROXY NETWORK (actors this entity sponsors):\n"
        f"{proxy_block}\n"
        f"\n"
        f"PEER ACTORS — same type, currently scored ({len(peers)} found):\n"
        f"{peers_block}\n"
        f"\n"
        f"LINKED EVENTS ({len(linked_events)}):\n"
        f"{events_block}\n"
        f"\n"
        f"LINKED CASE STUDIES ({len(linked_case_studies)}):\n"
        f"{cs_block}\n"
        f"\n"
        "Score this actor. Check anchor consistency first. Then apply events and "
        "relationship context. The patron ceiling above is a hard constraint — "
        "do not exceed it. Peers are calibration reference only — do not blindly "
        "converge to them. Return only the JSON object."
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
