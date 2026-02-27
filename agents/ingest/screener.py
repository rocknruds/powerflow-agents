"""PDF relevance screener for the PowerFlow geopolitical intelligence system.

Accepts a PDF file path, extracts text, and returns a structured relevance
assessment using the Anthropic API. Stateless — writes nothing to Notion.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import anthropic
import pdfplumber
from dotenv import load_dotenv

load_dotenv()

_ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
_SCREENER_MODEL = os.getenv("CLAUDE_SCREENER_MODEL", os.getenv("CLAUDE_MODEL", "claude-sonnet-4-5"))
_MAX_TOKENS = 1024

_NOTION_DATABASES = [
    "Events Timeline",
    "Actors Registry",
    "PowerFlow Assessments",
    "Conflicts Registry",
    "Geopolitical Units",
    "Scenarios & Stress Tests",
]

_SYSTEM_PROMPT = """\
You are a senior analyst for PowerFlow, a geopolitical intelligence system that tracks \
the gap between declared sovereignty and exercised authority — where power actually moves \
versus where it is officially claimed to reside.

Your task is to screen a document for relevance to the PowerFlow intelligence mission.

---

STEP 1 — SCORE FIVE DIMENSIONS INDEPENDENTLY (0-20 each)

Before producing a final score, evaluate the document on exactly five dimensions. \
Each dimension is worth 0-20 points. Be strict — do not round up out of generosity.

1. SOVEREIGNTY GAP CENTRALITY (0-20)
   Is the sovereignty gap — the divergence between claimed authority and actual control — \
   the PRIMARY subject of this document, or merely backdrop?
   - 18-20: Sovereignty gap dynamics are the explicit analytical core (e.g. a state losing \
     territorial control, a non-state actor exercising governance, a regime's authority \
     being contested by a rival power structure)
   - 12-17: Sovereignty gap is a major theme but the article is partly about something else \
     (diplomacy, economics, personalities)
   - 6-11: Sovereignty gap is present but incidental — the article is about something else \
     and the gap angle requires inference
   - 0-5: No meaningful sovereignty gap signal. Political figures mentioned but gap is not \
     the subject.

2. ACTOR RELEVANCE (0-20)
   Does the document involve actors PowerFlow tracks or should track — states, \
   non-state armed groups, proxy forces, IGOs, or individuals exercising real authority?
   - 18-20: Multiple clearly trackable actors with specific roles (e.g. named armed groups, \
     state security services, proxy patrons, individual powerbrokers)
   - 12-17: At least one clearly trackable actor, others are generic or institutional
   - 6-11: Only generic state references ("the government", "officials") with no specific \
     actor detail
   - 0-5: No trackable actors. Private sector entities, celebrities, or civilians only.

3. EVENT ACTIONABILITY (0-20)
   Does this document describe a discrete, datable event or structural change that belongs \
   in PowerFlow's Events Timeline — something that happened, shifted, or was decided?
   - 18-20: Clear, specific event with date, actors, and consequence (military action, \
     treaty shift, institutional change, sanctions, coup, election result)
   - 12-17: Event is described but lacks specificity in date, actors, or consequence
   - 6-11: Background or analytical piece — describes trends rather than discrete events
   - 0-5: No event. Pure opinion, forecast without trigger, or historical retrospective \
     with no current-period update.

4. GEOGRAPHIC / THEMATIC SCOPE (0-20)
   Does the document cover regions or themes that PowerFlow actively tracks or \
   should expand into?
   - 18-20: Core tracked region (Middle East, South Asia, Horn of Africa, post-Soviet space, \
     Latin America narco-states) with direct relevance to existing case studies or conflicts
   - 12-17: Tracked region but peripheral to existing case studies, OR a new region \
     with strong sovereignty gap signal worth opening a new thread
   - 6-11: Partially relevant geography or theme — touches tracked areas tangentially
   - 0-5: Entirely outside PowerFlow's geographic or thematic scope with no expansion case.

5. SOURCE QUALITY & INTELLIGENCE DENSITY (0-20)
   How much new, specific, verifiable intelligence does this document add — \
   and how reliable is the source?
   - 18-20: Primary source reporting with named officials, documentary evidence, or \
     on-the-ground detail. High-density new intelligence.
   - 12-17: Good secondary reporting with specific claims, multiple sources, \
     or strong institutional credibility (major newspaper, think tank, UN report)
   - 6-11: Limited new intelligence — repackages known information, thin sourcing, \
     or editorial/opinion framing
   - 0-5: No new intelligence. Speculation, unverified claims, or pure commentary.

---

STEP 2 — APPLY EXCLUSION PENALTIES

After scoring, apply these penalties before summing:

- AUTOMATIC CAP AT 35 if the document is primarily about: corporate deals, \
  entertainment, sports, technology products, or domestic economic policy where \
  geopolitics is backdrop not subject.
- DEDUCT 10 if political figures appear only in a business/personal capacity \
  with no governance or authority implications.
- DEDUCT 5 if the article is more than 6 months old and describes no ongoing \
  structural condition (i.e. a dated event with no current relevance).

Key test: "Is the sovereignty gap the SUBJECT of this document, or merely a backdrop?" \
If backdrop, cap Sovereignty Gap Centrality at 8 maximum.

---

STEP 3 — SUM AND OUTPUT

Final score = sum of five dimension scores, minus any penalties. \
Clamp to 0-100.

Verdict tiers:
- 70-100: Strong Match
- 40-69: Moderate Match  
- 10-39: Weak Match
- 0-9: Not Relevant

---

SCORE ANCHORS — use these as calibration references:

- 95: NYT report on Pakistani airstrikes inside Afghanistan with named military commanders, \
  specific targets, and confirmed Taliban TTP weapons transfers. Core sovereignty gap event, \
  high actor density, discrete datable action, tracked geography, primary source reporting.
- 80: Think tank analysis of RSF proxy network in Sudan with specific UAE funding \
  mechanisms. Strong gap centrality, good actor detail, structural rather than event-based, \
  credible source.
- 65: Reuters article on Ethiopian federal government negotiations with Tigray regional \
  authorities. Sovereignty gap relevant but negotiations are inconclusive, actors somewhat \
  generic, geography is tracked but peripheral to current case studies.
- 45: FT article on Saudi Arabia's Vision 2030 economic reforms mentioning regional \
  stability implications. Gap angle requires inference, no discrete event, actors are \
  institutional, intelligence density is low.
- 25: Politico piece on US Senate debate over Sudan sanctions. Mentions RSF indirectly, \
  but the subject is domestic US politics, no new intelligence on Sudan itself, \
  no sovereignty gap event.
- 10: Bloomberg article on UAE sovereign wealth fund investing in European real estate. \
  UAE is a tracked actor but the subject is a private financial transaction with no \
  governance or authority implications.
- 2: TMZ article mentioning a politician attended a film premiere. No relevance.

---

Respond ONLY with a valid JSON object using this exact structure:
{
  "dimension_scores": {
    "sovereignty_gap_centrality": <0-20>,
    "actor_relevance": <0-20>,
    "event_actionability": <0-20>,
    "geographic_scope": <0-20>,
    "source_quality": <0-20>
  },
  "penalties": <integer, 0 or negative>,
  "score": <integer 0-100, sum of dimensions plus penalties, clamped>,
  "verdict": "<Strong Match | Moderate Match | Weak Match | Not Relevant>",
  "reasoning": "<2-3 sentences explaining the score with reference to specific content>",
  "affected_databases": [<list of Notion database names likely to need updates>],
  "key_signals": [<list of 3-5 short strings describing specific relevant content found>]
}

Affected databases must be drawn only from this list:
Events Timeline, Actors Registry, PowerFlow Assessments, Conflicts Registry, \
Geopolitical Units, Scenarios & Stress Tests

CRITICAL: Return ONLY the JSON object. No markdown, no commentary. Start with { and end with }.\
"""


def extract_text_from_pdf(pdf_path: str | Path) -> str:
    """Extract all text from a PDF using pdfplumber."""
    text_parts: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)
    return "\n\n".join(text_parts)


def screen(pdf_path: str | Path) -> dict[str, Any]:
    """Screen a PDF for relevance to the PowerFlow intelligence mission.

    Args:
        pdf_path: Path to the PDF file to screen.

    Returns:
        A dict with keys: score, verdict, reasoning, affected_databases, key_signals.

    Raises:
        ValueError: If the PDF cannot be parsed or the API returns malformed JSON.
        RuntimeError: If the Anthropic API call fails.
    """
    text = extract_text_from_pdf(pdf_path)
    if not text.strip():
        raise ValueError("Could not extract any text from the PDF.")

    # Truncate to avoid token limits while preserving most content
    max_chars = 60_000
    if len(text) > max_chars:
        text = text[:max_chars] + "\n\n[Document truncated for screening]"

    client = anthropic.Anthropic(api_key=_ANTHROPIC_API_KEY)

    try:
        message = client.messages.create(
            model=_SCREENER_MODEL,
            max_tokens=_MAX_TOKENS,
            system=[
                {
                    "type": "text",
                    "text": _SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": f"Screen the following document:\n\n{text}"}],
        )
    except anthropic.APIError as exc:
        raise RuntimeError(f"Anthropic API error during screening: {exc}") from exc

    raw = message.content[0].text.strip()
    return _parse_and_validate(raw)


def _parse_and_validate(raw: str) -> dict[str, Any]:
    """Parse and validate the screener response JSON."""
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()

    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON object found in screener response:\n{raw}")

    data = json.loads(match.group())

    score = int(data.get("score", 0))
    score = max(0, min(100, score))

    valid_verdicts = {"Strong Match", "Moderate Match", "Weak Match", "Not Relevant"}
    verdict = data.get("verdict", "Not Relevant")
    if verdict not in valid_verdicts:
        if score >= 70:
            verdict = "Strong Match"
        elif score >= 40:
            verdict = "Moderate Match"
        elif score >= 10:
            verdict = "Weak Match"
        else:
            verdict = "Not Relevant"

    affected_databases = [
        db for db in data.get("affected_databases", []) if db in _NOTION_DATABASES
    ]

    key_signals = data.get("key_signals", [])
    if isinstance(key_signals, list):
        key_signals = [str(s) for s in key_signals[:5]]
    else:
        key_signals = []

    result: dict[str, Any] = {
        "score": score,
        "verdict": verdict,
        "reasoning": str(data.get("reasoning", "")),
        "affected_databases": affected_databases,
        "key_signals": key_signals,
    }

    raw_dims = data.get("dimension_scores")
    if isinstance(raw_dims, dict):
        _dim_keys = {
            "sovereignty_gap_centrality",
            "actor_relevance",
            "event_actionability",
            "geographic_scope",
            "source_quality",
        }
        result["dimension_scores"] = {
            k: max(0, min(20, int(v)))
            for k, v in raw_dims.items()
            if k in _dim_keys and isinstance(v, (int, float))
        }

    penalties = data.get("penalties")
    if isinstance(penalties, (int, float)):
        result["penalties"] = int(penalties)

    return result
