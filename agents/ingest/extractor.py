"""LLM extraction via the Anthropic SDK."""

import json
import re
from typing import Any

import anthropic
from rich.console import Console

from config.settings import (
    ANTHROPIC_API_KEY,
    CLAUDE_MAX_TOKENS,
    CLAUDE_MODEL,
    VALID_ACTOR_TYPES,
    VALID_EVENT_TYPES,
    VALID_PF_SIGNAL_IMPACTS,
    VALID_RELIABILITY,
    VALID_SOURCE_TYPES,
)

console = Console()

ACTOR_NAME_VARIANTS: dict[str, str] = {
    "russia": "Russia",
    "russian federation": "Russia",
    "the russian federation": "Russia",
    "united states": "United States",
    "united states of america": "United States",
    "the united states": "United States",
    "usa": "United States",
    "u.s.": "United States",
    "us": "United States",
    "china": "China (CCP)",
    "people's republic of china": "China (CCP)",
    "prc": "China (CCP)",
    "ccp": "China (CCP)",
    "iran": "Iran",
    "islamic republic of iran": "Iran",
    "taliban": "Afghanistan (Taliban)",
    "islamic emirate of afghanistan": "Afghanistan (Taliban)",
    "houthis": "Houthis",
    "ansar allah": "Houthis",
    "hezbollah": "Hezbollah",
    "party of god": "Hezbollah",
    "irgc": "IRGC",
    "islamic revolutionary guard corps": "IRGC",
    "isis": "ISIS",
    "islamic state": "ISIS",
    "isil": "ISIS",
    "daesh": "ISIS",
    "ttp": "Tehreek-e-Taliban Pakistan (TTP)",
    "tehreek-e-taliban": "Tehreek-e-Taliban Pakistan (TTP)",
    "pmf": "Iraq (PMF)",
    "popular mobilization forces": "Iraq (PMF)",
    "rsf": "Rapid Support Forces (RSF)",
    "rapid support forces": "Rapid Support Forces (RSF)",
    "uae": "United Arab Emirates",
    "united arab emirates": "United Arab Emirates",
    "uk": "United Kingdom",
    "united kingdom": "United Kingdom",
    "great britain": "United Kingdom",
}


def normalize_actor_name(name: str) -> str:
    """Return the canonical actor name for known variants, or title-case the original."""
    key = name.lower().strip()
    return ACTOR_NAME_VARIANTS.get(key, name.strip().title())


_SYSTEM_PROMPT = """\
You are a geopolitical intelligence analyst working within the PowerFlow system.
PowerFlow scores how power actually moves through the world — measuring real-world
control and influence, not nominal or claimed authority. Your job is to extract
structured intelligence that helps update those scores.

Your task is to extract structured intelligence from the provided article or text.
Return ONLY a valid JSON object with no additional text, commentary, or markdown.

Extraction rules:
- Be precise and analytical, not journalistic
- Event names should be concise and descriptive
  (e.g. "Russia Suspends New START Treaty Participation" not "Russia and US nuclear treaty")
- Descriptions should focus on structural power implications, not just what happened
- PF Signal must reflect the net direction of power gap movement across this event.
  Choose the single best option:
    "Widening" — event expands the gap between claimed and exercised power for a key actor
                 (actor loses effective control or influence)
    "Narrowing" — event reduces that gap (actor consolidates control or gains influence)
    "Mixed"    — different actors move in opposite directions within the same event
    "Stable"   — no meaningful score movement expected; event is noise not signal
    "Unclear"  — LAST RESORT ONLY. Use only when the article genuinely provides
                 insufficient information to make any assessment. Do not default here;
                 if you can reason about power implications at all, choose one of the above.
- If the date is unclear, use the article publication date
- Reliability: High = established outlet or primary source,
  Medium = secondary reporting, Low = unverified or opinion
- Source Type: classify based on the publishing organization.
  Use "Analytical / Longform" for in-depth analytical essays, longform journalism, or extended commentary pieces that are neither strictly academic nor standard news reporting.
- Author vs. Publication: these are always separate fields. "publication" must contain only the outlet or institution name. "author" must contain only the individual person's byline name. Never combine them into either field.

Return this exact JSON structure:
{
  "source": {
    "title": "string",
    "publication": "string — the outlet or institution name ONLY (e.g. 'New York Times', 'WSJ', 'CSIS', 'RAND Corporation'). Never a person's name. Never combine author and publication.",
    "author": "string — the individual author's name (e.g. 'Jane Smith'). First and last name only. Leave blank if no individual byline is present. Never combine with the publication name.",
    "publication_date": "YYYY-MM-DD",
    "source_type": "Academic | Government | News | Think tank | OSINT | Legal document | Analytical / Longform | Other",
    "reliability": "High | Medium | Low",
    "summary": "string (2-3 sentences — capture the author's core analytical argument, not just the topic)"
  },
  "event": {
    "event_name": "string",
    "date": "YYYY-MM-DD",
    "event_type": "Legal change | Military or coercive action | Sanctions or economic measure | Institutional reform | Alliance or treaty shift | Information-cyber | Other",
    "description": "string (3-5 sentences, analytically focused on power implications)",
    "pf_signal": "Widening | Narrowing | Mixed | Stable | Unclear",
    "mechanism": "string (1-2 sentences — the specific causal pathway through which this event affects real-world control or influence. Not what happened — WHY and HOW it changes power. Example: 'Destruction of IRGC command infrastructure severs Iran's proxy coordination network, removing the financial and logistics pipelines that enabled cross-theater reach projection.')",
    "trajectory": "string (1-2 sentences — is this a structural shift or a cyclical/temporary disruption? What is the realistic recovery pathway and timeframe? Example: 'Structural degradation — IRGC reconstitution historically requires 5-10 years; proxy realignment contingent on successor patron emergence with no clear precedent in this theater.')"
  },
  "actors": [
    {
      "name": "string — canonical name of the actor",
      "actor_type": "State | Non-State | Hybrid | IGO | Individual",
      "sub_type": "string — for Individual actors: always 'Influential Figure'. For all others: null",
      "region": "string — infer from the actor's primary geography. Use one of: Middle East, Russia-FSU, Europe, South Asia, East Asia, Sub-Saharan Africa, North Africa, Latin America, Global",
      "capabilities": ["array — select ALL applicable from: Conventional Military, Asymmetric / Guerrilla, Nuclear, Cyber, Economic Leverage, Intelligence Networks, Proxy Sponsorship, Information Warfare, Territorial Control, Legal / Diplomatic. Infer from context — prefer an imperfect populated list over an empty one."],
      "pf_vector": "string — the actor's primary power vector in this event. Choose one: From Below (Challenger) | From Above (External Pressure) | From Within (Parallel Governance) | Defender | Neutral. Infer from role in event.",
      "proxy_depth": "string — this actor's position in proxy/patron hierarchies. Choose one: Patron | Principal | Agent | Autonomous | None. Use 'None' for fully independent sovereign actors with no proxy relationship in this event.",
      "role_in_event": "string — one sentence on what this actor did or experienced",
      "pf_implication": "string — one sentence on what this event means for this actor's power trajectory going forward, not what happened",
      "analytical_notes": "string — for Individual actors only: factual background on this person — their history, key relationships, and organizational role. Separate from analytical interpretation. Null for non-individual actors.",
      "pf_relevance": "string — for Individual actors only: why this person is relevant to PowerFlow's world model and how they affect power dynamics. Null for non-individual actors.",
      "iso3": "string — ISO 3166-1 alpha-3 country code if applicable, else null"
    }
  ],
  "intel_feed": {
    "so_what_summary": "string (2-3 sentences — analytical summary of what this document means for PowerFlow's world model: what changed, for which actors, and what it implies. This is NOT a description of the document. Write it as a finished analytical statement, e.g. 'Russia's suspension of New START removes the last bilateral arms-control mechanism, freeing Moscow to expand its tactical nuclear posture without transparency obligations. This shifts the strategic calculus for NATO's eastern flank states, accelerating their push for Article 5 tripwire deployments. The gap between Russia's claimed compliance posture and its actual force posture is now unverifiable, widening PF scores across the Russia-NATO axis.')",
    "mechanism": "string (1-2 sentences — same causal argument as event.mechanism but written for the Intel Feed analytical layer)",
    "trajectory": "string (1-2 sentences — same durability claim as event.trajectory but from the Intel Feed perspective)",
    "cascade_effects": "string (2-4 sentences — the multi-hop downstream chain this event sets in motion across actors and regions. Trace the second and third-order effects. Example: 'IRGC collapse removes the coordination backbone for Houthi operations, likely degrading Red Sea interdiction tempo within 60-90 days. Normalized shipping lanes reduce Gulf insurance premiums, easing Turkey's export corridor economics and reducing pressure on Erdogan to seek alternative trade routes. Qatar's regional mediation leverage increases as Iran's axis fractures and Gulf states seek a new broker.')",
    "analyst_affiliation": "string — if the author is affiliated with a think tank, research institute, or academic institution (e.g. 'Carnegie Endowment', 'RAND Corporation', 'Brookings Institution'), populate with the institution name. Leave blank for journalists at news outlets."
  }
}

Actor extraction rules:
- Extract only actors that exercise independent decision-making authority relevant to this event
- INCLUDE: sovereign states, non-state armed groups, international organizations, heads of state/government, or the primary named decision-maker driving the event
- DO NOT extract: military commands (CENTCOM, AFRICOM), government departments (Pentagon, State Dept, Treasury), legislative bodies (Congress, Knesset), or advisory bodies (Joint Chiefs) — these are sub-units of the parent state actor
- DO NOT extract generic references like 'the public', 'citizens', or unnamed officials
- For individuals: only extract heads of state/government OR the single named central decision-maker with no parent state actor already covering their role
- If both a state and its head of state appear, include both
- Aim for 2-5 actors per article
- iso3: ISO 3166-1 alpha-3 of the actor's primary country, or null
- capabilities: always populate this array. Infer from the actor's known role, type, and behavior in the article. An imperfect inference flagged for human review is better than an empty array.
- pf_vector and proxy_depth: always populate. Use context and actor type to infer reasonable values.

Source quality guidance:
- For think tank and academic sources: summary should capture the author's core analytical claim and evidence base, not just the topic
- For longform journalism: surface the structural observation buried in the piece, not the lede
"""

_STRICT_SUFFIX = (
    "\n\nCRITICAL: Return ONLY the JSON object. "
    "No markdown fences, no commentary, no explanation. "
    "The response must start with { and end with }."
)


def extract(text: str) -> dict[str, Any]:
    """Send article text to Claude and return the parsed extraction dict.

    Retries once with a stricter prompt if the first response is malformed JSON.
    Raises RuntimeError if both attempts fail.
    """
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    raw = _call_claude(client, text, strict=False)
    try:
        data = _parse_json(raw)
    except ValueError:
        console.print(
            "[yellow]Warning:[/yellow] Claude returned malformed JSON. Retrying with stricter prompt..."
        )
        raw = _call_claude(client, text, strict=True)
        try:
            data = _parse_json(raw)
        except ValueError as exc:
            raise RuntimeError(
                f"Claude returned malformed JSON on both attempts.\nRaw response:\n{raw}"
            ) from exc

    return _validate_and_coerce(data)


def _call_claude(client: anthropic.Anthropic, text: str, strict: bool) -> str:
    system_text = _SYSTEM_PROMPT + (_STRICT_SUFFIX if strict else "")
    message = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=CLAUDE_MAX_TOKENS,
        system=[
            {
                "type": "text",
                "text": system_text,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": text}],
    )
    return message.content[0].text.strip()


def _parse_json(raw: str) -> dict[str, Any]:
    """Extract and parse JSON from the response string."""
    # Strip markdown fences if present
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()

    # Find the outermost JSON object
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        raise ValueError("No JSON object found in response")

    return json.loads(match.group())


def _validate_and_coerce(data: dict[str, Any]) -> dict[str, Any]:
    """Validate enum fields against allowed values, defaulting to 'Other' with a warning."""
    source = data.get("source", {})
    event = data.get("event", {})
    actors: list[dict[str, Any]] = data.get("actors", [])
    intel_feed: dict[str, Any] = data.get("intel_feed", {})

    source["source_type"] = _coerce(
        source.get("source_type", ""), VALID_SOURCE_TYPES, "source.source_type"
    )
    source["reliability"] = _coerce(
        source.get("reliability", ""), VALID_RELIABILITY, "source.reliability"
    )
    event["event_type"] = _coerce(
        event.get("event_type", ""), VALID_EVENT_TYPES, "event.event_type"
    )
    event["pf_signal"] = _coerce(
        event.get("pf_signal", ""),
        VALID_PF_SIGNAL_IMPACTS,
        "event.pf_signal",
        default="Unclear",
    )

    valid_capabilities = {
        "Conventional Military", "Asymmetric / Guerrilla", "Nuclear", "Cyber",
        "Economic Leverage", "Intelligence Networks", "Proxy Sponsorship",
        "Information Warfare", "Territorial Control", "Legal / Diplomatic",
    }
    valid_pf_vectors = {
        "From Below (Challenger)", "From Above (External Pressure)",
        "From Within (Parallel Governance)", "Defender", "Neutral",
    }
    valid_proxy_depths = {"Patron", "Principal", "Agent", "Autonomous", "None"}

    validated_actors: list[dict[str, Any]] = []
    for actor in actors:
        if not isinstance(actor, dict):
            continue
        actor["name"] = normalize_actor_name(actor.get("name", ""))
        actor["actor_type"] = _coerce(
            actor.get("actor_type", ""),
            VALID_ACTOR_TYPES,
            f"actors[{actor.get('name', '?')}].actor_type",
            default="Non-State",
        )
        # Normalize iso3: keep only non-empty strings, coerce null/None to None
        iso3 = actor.get("iso3")
        actor["iso3"] = iso3 if isinstance(iso3, str) and iso3.strip() else None
        sub_type = actor.get("sub_type")
        actor["sub_type"] = sub_type if isinstance(sub_type, str) and sub_type.strip() else None
        pf_implication = actor.get("pf_implication")
        actor["pf_implication"] = pf_implication if isinstance(pf_implication, str) and pf_implication.strip() else None
        region = actor.get("region")
        actor["region"] = region if isinstance(region, str) and region.strip() else None
        # Filter capabilities to only valid options
        raw_caps = actor.get("capabilities")
        if isinstance(raw_caps, list):
            actor["capabilities"] = [c for c in raw_caps if c in valid_capabilities]
        else:
            actor["capabilities"] = []
        # Coerce pf_vector and proxy_depth
        actor["pf_vector"] = _coerce(
            actor.get("pf_vector", "") or "",
            valid_pf_vectors,
            f"actors[{actor.get('name', '?')}].pf_vector",
            default="Neutral",
        )
        actor["proxy_depth"] = _coerce(
            actor.get("proxy_depth", "") or "",
            valid_proxy_depths,
            f"actors[{actor.get('name', '?')}].proxy_depth",
            default="None",
        )
        validated_actors.append(actor)

    return {"source": source, "event": event, "actors": validated_actors, "intel_feed": intel_feed}


def _coerce(value: str, valid_set: set[str], field_name: str, default: str = "Other") -> str:
    if value in valid_set:
        return value
    console.print(
        f"[yellow]Warning:[/yellow] '{value}' is not a valid value for [bold]{field_name}[/bold]. "
        f"Defaulting to '{default}'."
    )
    return default
