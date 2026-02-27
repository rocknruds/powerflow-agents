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
    VALID_RELIABILITY,
    VALID_SOVEREIGNTY_IMPACTS,
    VALID_SOURCE_TYPES,
)

console = Console()

_SYSTEM_PROMPT = """\
You are a geopolitical intelligence analyst working within the PowerFlow system. \
PowerFlow analyzes the gap between declared sovereignty and exercised authority — \
where power actually moves versus where it is officially claimed to reside.

Your task is to extract structured intelligence from the provided article or text. \
Return ONLY a valid JSON object with no additional text, commentary, or markdown.

Extraction rules:
- Be precise and analytical, not journalistic
- Event names should be concise and descriptive \
(e.g. "Russia Suspends New START Treaty Participation" not "Russia and US nuclear treaty")
- Descriptions should focus on structural power implications, not just what happened
- Impact on Sovereignty Gap must reflect whether this event expands or contracts the gap \
between a state's claimed authority and its actual control
- If the date is unclear, use the article publication date
- Reliability: High = established outlet or primary source, \
Medium = secondary reporting, Low = unverified or opinion
- Source Type: classify based on the publishing organization

Return this exact JSON structure:
{
  "source": {
    "title": "string",
    "author_organization": "string",
    "publication_date": "YYYY-MM-DD",
    "source_type": "Academic | Government | News | Think tank | OSINT | Legal document | Other",
    "reliability": "High | Medium | Low",
    "summary": "string (2-3 sentences)"
  },
  "event": {
    "event_name": "string",
    "date": "YYYY-MM-DD",
    "event_type": "Legal change | Military or coercive action | Sanctions or economic measure | Institutional reform | Alliance or treaty shift | Information-cyber | Other",
    "description": "string (3-5 sentences, analytically focused on power implications)",
    "impact_on_sovereignty_gap": "Widens | Narrows | No clear effect | Indirect"
  },
  "actors": [
    {
      "name": "string — canonical name of the actor",
      "actor_type": "State | Non-State | Hybrid | IGO | Individual",
      "role_in_event": "string — one sentence describing what this actor did in the article",
      "iso3": "string — ISO 3166-1 alpha-3 country code if applicable, else null"
    }
  ]
}

Actor extraction rules:
- Extract all meaningful actors: states, governments, armed groups, individuals in official capacity, international organizations
- Do NOT extract generic references such as 'the public', 'citizens', or 'local population'
- Aim for 2-6 actors per article
- Use the canonical, full name for each actor (e.g. "United States" not "US", "Wagner Group" not "Wagner")
- iso3 should be the ISO 3166-1 alpha-3 code of the actor's primary country (e.g. "USA", "RUS"), or null if not applicable\
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

    source["source_type"] = _coerce(
        source.get("source_type", ""), VALID_SOURCE_TYPES, "source.source_type"
    )
    source["reliability"] = _coerce(
        source.get("reliability", ""), VALID_RELIABILITY, "source.reliability"
    )
    event["event_type"] = _coerce(
        event.get("event_type", ""), VALID_EVENT_TYPES, "event.event_type"
    )
    event["impact_on_sovereignty_gap"] = _coerce(
        event.get("impact_on_sovereignty_gap", ""),
        VALID_SOVEREIGNTY_IMPACTS,
        "event.impact_on_sovereignty_gap",
    )

    validated_actors: list[dict[str, Any]] = []
    for actor in actors:
        if not isinstance(actor, dict):
            continue
        actor["actor_type"] = _coerce(
            actor.get("actor_type", ""),
            VALID_ACTOR_TYPES,
            f"actors[{actor.get('name', '?')}].actor_type",
            default="Non-State",
        )
        # Normalize iso3: keep only non-empty strings, coerce null/None to None
        iso3 = actor.get("iso3")
        actor["iso3"] = iso3 if isinstance(iso3, str) and iso3.strip() else None
        validated_actors.append(actor)

    return {"source": source, "event": event, "actors": validated_actors}


def _coerce(value: str, valid_set: set[str], field_name: str, default: str = "Other") -> str:
    if value in valid_set:
        return value
    console.print(
        f"[yellow]Warning:[/yellow] '{value}' is not a valid value for [bold]{field_name}[/bold]. "
        f"Defaulting to '{default}'."
    )
    return default
