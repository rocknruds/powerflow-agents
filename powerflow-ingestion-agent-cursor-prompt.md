# PowerFlow Ingestion Agent — Cursor Build Prompt

## Context

You are building the first agent for **PowerFlow**, a geopolitical intelligence system that maps the gap between claimed authority and exercised control. This repo is the **agents layer** — separate from the public-facing Next.js frontend.

This agent's job: accept a URL or pasted article text, extract structured geopolitical event data from it using Claude, and write two records to Notion — one to the **Sources** database and one to the **Events / Structural Changes Timeline** database.

---

## Repo Structure to Create

```
powerflow-agents/
├── agents/
│   └── ingest/
│       ├── __init__.py
│       ├── scraper.py        # URL fetching and text extraction
│       ├── extractor.py      # LLM extraction via Anthropic SDK
│       ├── notion_writer.py  # Notion API writes
│       └── run.py            # CLI entrypoint
├── config/
│   └── settings.py           # Env vars and constants
├── .env.example
├── requirements.txt
└── README.md
```

---

## Stack

- **Python 3.11+**
- **anthropic** — Claude API for extraction
- **notion-client** — official Notion Python SDK
- **requests** + **beautifulsoup4** — URL scraping
- **python-dotenv** — env management
- **rich** — CLI output formatting

---

## Environment Variables (.env)

```
ANTHROPIC_API_KEY=your_key_here
NOTION_API_KEY=your_notion_integration_key
```

---

## Notion Database IDs

These are the exact Notion data source collection IDs to write to:

| Database | Collection ID |
|---|---|
| Events / Structural Changes Timeline | `21452f2f-6f38-4a70-8f3b-dabbb7ee81f1` |
| Sources | `c0e5c418-893f-4138-bc0d-7d046b02323d` |

The Notion page IDs (used for creating pages via the API) are:
- Events database page ID: `70e9768bfcec49a9aa8565d5aa1f1881`
- Sources database page ID: `0c3415c21d944845841665bdcd1c529e`

---

## Exact Notion Property Schemas

### Sources Database
| Property | Type | Valid Values |
|---|---|---|
| Title | title | Free text — article/document title |
| URL | url | The source URL |
| Source Type | select | `Academic`, `Government`, `News`, `Think tank`, `OSINT`, `Legal document`, `Other` |
| Reliability | select | `High`, `Medium`, `Low` |
| Author / Organization | rich_text | Free text |
| Publication Date | date | ISO-8601 date string |
| Summary | rich_text | 2–3 sentence summary of the source |

### Events / Structural Changes Timeline Database
| Property | Type | Valid Values |
|---|---|---|
| Event Name | title | Short, descriptive event name |
| Date | date | ISO-8601 date string |
| Event Type | select | `Legal change`, `Military or coercive action`, `Sanctions or economic measure`, `Institutional reform`, `Alliance or treaty shift`, `Information-cyber`, `Other` |
| Description | rich_text | 3–5 sentence analytical description |
| Impact on Sovereignty Gap | select | `Widens`, `Narrows`, `No clear effect`, `Indirect` |
| Key Sources | relation | Link to the Source page created in the same run |

---

## Agent Flow

```
1. User provides URL or raw text via CLI
2. If URL: scrape and extract clean article text (strip nav, ads, boilerplate)
3. Send text to Claude with the extraction prompt (see below)
4. Claude returns structured JSON
5. Validate the JSON against allowed enum values
6. Write Source record to Notion → capture returned page ID
7. Write Event record to Notion → link Key Sources to Source page ID
8. Print confirmation with Notion page URLs
```

---

## Claude Extraction Prompt

Use this system prompt exactly when calling the Anthropic API:

```
You are a geopolitical intelligence analyst working within the PowerFlow system. PowerFlow analyzes the gap between declared sovereignty and exercised authority — where power actually moves versus where it is officially claimed to reside.

Your task is to extract structured intelligence from the provided article or text. Return ONLY a valid JSON object with no additional text, commentary, or markdown.

Extraction rules:
- Be precise and analytical, not journalistic
- Event names should be concise and descriptive (e.g. "Russia Suspends New START Treaty Participation" not "Russia and US nuclear treaty")
- Descriptions should focus on structural power implications, not just what happened
- Impact on Sovereignty Gap must reflect whether this event expands or contracts the gap between a state's claimed authority and its actual control
- If the date is unclear, use the article publication date
- Reliability: High = established outlet or primary source, Medium = secondary reporting, Low = unverified or opinion
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
  }
}
```

---

## CLI Interface

The agent should be runnable two ways:

```bash
# From URL
python -m agents.ingest.run --url "https://example.com/article"

# From pasted text (reads from stdin)
python -m agents.ingest.run --text "paste article text here"

# Interactive mode (prompts for input)
python -m agents.ingest.run
```

Output should use `rich` to show:
- Extraction results in a formatted panel before writing
- Confirmation with ✓ and Notion page URLs after writing
- Clear error messages if scraping or API calls fail

---

## Error Handling Requirements

- If scraping fails (paywalled, JS-rendered, etc.), print a clear error and exit gracefully — do not crash
- If Claude returns malformed JSON, retry once with a stricter prompt, then exit with error
- If a select value from Claude doesn't match valid options, default to `Other` and flag it in the CLI output
- If Notion write fails, print the full error response — do not silently fail

---

## Important Notes

- Do NOT link Geopolitical Units in v1 — that relation requires fuzzy-matching against an existing database and will be handled in a future agent
- Do NOT create Actor records in v1 — actors are referenced in the description text only
- The Notion integration key must have access to the PowerFlow workspace. Confirm this is set up before running.
- Use `claude-haiku-4-5-20251001` as the model for extraction — it's fast and more than capable for structured JSON extraction tasks
- Always set `max_tokens=1024` for the extraction call — the JSON response is small

---

## README Content

The README should explain:
1. What PowerFlow Agents is
2. How to set up the .env
3. How to get a Notion integration key and share the databases with it
4. How to run the ingestion agent
5. What gets written to Notion and where to find it
