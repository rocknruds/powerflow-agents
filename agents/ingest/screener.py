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

Your task is to screen a PDF document for relevance to the PowerFlow intelligence mission. \
Evaluate whether the document contains actionable intelligence across any of these dimensions:

- New geopolitical events or developments (territorial, diplomatic, military)
- Actor movements: state actors, non-state armed groups, international institutions, \
  oligarchic networks, or proxy forces
- Sovereignty gap signals: areas where claimed authority diverges from actual control
- Conflict updates: kinetic, hybrid, economic, or information warfare developments
- Structural authority shifts: institutional changes, elections, coups, sanctions regimes, \
  treaty changes, or governance collapses
- Regional relevance to any tracked area of geopolitical significance

Respond ONLY with a valid JSON object using this exact structure:
{
  "score": <integer 0-100>,
  "verdict": "<Strong Match | Moderate Match | Weak Match | Not Relevant>",
  "reasoning": "<2-3 sentence explanation of why this score was assigned>",
  "affected_databases": [<list of Notion database names likely to need updates>],
  "key_signals": [<list of 3-5 short strings describing specific relevant content found>]
}

EXCLUSION CRITERIA — automatically score below 30 if the article is primarily about:
- Corporate mergers, acquisitions, or business deals where geopolitics is incidental
- Entertainment, media, sports, or cultural industries
- Domestic economic policy without clear sovereignty gap implications
- Technology companies or products without direct state/conflict relevance
- Any story where the primary subject is a private sector transaction

The presence of political figures in a business context does NOT make an article geopolitically \
relevant. Ask: is the sovereignty gap the SUBJECT of this article, or merely a backdrop?

Scoring guidance:
- 70–100: Strong Match — directly actionable, clear new intelligence on tracked themes
- 40–69: Moderate Match — relevant context or secondary intelligence worth review
- 10–39: Weak Match — tangentially related, minimal actionable content
- 0–9: Not Relevant — no meaningful relevance to PowerFlow tracking mission

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
            system=_SYSTEM_PROMPT,
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

    return {
        "score": score,
        "verdict": verdict,
        "reasoning": str(data.get("reasoning", "")),
        "affected_databases": affected_databases,
        "key_signals": key_signals,
    }
