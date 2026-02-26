# PowerFlow Agents

PowerFlow is a geopolitical intelligence system that maps the gap between claimed authority and exercised control — tracking where power actually moves versus where it is officially declared to reside.

This repo contains the **agents layer**: autonomous Python scripts that ingest, extract, and write structured intelligence data into the PowerFlow Notion workspace.

---

## Agents

### Ingestion Agent (`agents/ingest`)

Accepts a URL or pasted article text, extracts structured geopolitical event data using Claude, and writes two records to Notion:

1. **Sources** — bibliographic metadata about the article
2. **Events / Structural Changes Timeline** — the extracted geopolitical event

---

## Setup

### 1. Python

Requires Python 3.11 or higher. Create and activate a virtual environment:

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment variables

Copy the example env file and fill in your keys:

```bash
cp .env.example .env
```

Edit `.env`:

```
ANTHROPIC_API_KEY=your_anthropic_api_key_here
NOTION_API_KEY=your_notion_integration_key_here
```

#### Getting an Anthropic API key

Sign up at [console.anthropic.com](https://console.anthropic.com) and create an API key under **API Keys**.

#### Getting a Notion integration key

1. Go to [notion.so/my-integrations](https://www.notion.so/my-integrations) and click **+ New integration**
2. Give it a name (e.g. "PowerFlow Agents"), select your workspace, and click **Submit**
3. Copy the **Internal Integration Token** — this is your `NOTION_API_KEY`
4. In Notion, open each of the two databases below, click **⋯ → Connections → Add connection**, and select your integration

| Database | Notion ID |
|---|---|
| Events / Structural Changes Timeline | `21452f2f-6f38-4a70-8f3b-dabbb7ee81f1` |
| Sources | `c0e5c418-893f-4138-bc0d-7d046b02323d` |

The integration must have **read and write** access to both databases.

---

## Running the Ingestion Agent

Run from the repo root:

```bash
# Ingest from a URL
python -m agents.ingest.run --url "https://example.com/article"

# Ingest from pasted text
python -m agents.ingest.run --text "Paste your article text here..."

# Interactive mode (prompts for URL or text)
python -m agents.ingest.run
```

The agent will:
1. Fetch and clean the article text (if a URL is provided)
2. Send the text to Claude for structured extraction
3. Display the extracted Source and Event data for review
4. Ask for confirmation before writing to Notion
5. Print the Notion page URLs on success

---

## What Gets Written to Notion

### Sources Database

| Field | Description |
|---|---|
| Title | Article/document title |
| URL | Source URL (if ingested from a URL) |
| Source Type | Academic, Government, News, Think tank, OSINT, Legal document, or Other |
| Reliability | High, Medium, or Low |
| Author / Organization | Byline or publishing organization |
| Publication Date | ISO date |
| Summary | 2–3 sentence summary |

### Events / Structural Changes Timeline Database

| Field | Description |
|---|---|
| Event Name | Concise, descriptive event label |
| Date | ISO date of the event |
| Event Type | Legal change, Military or coercive action, Sanctions, Institutional reform, etc. |
| Description | 3–5 sentence analytical description focused on power implications |
| Impact on Sovereignty Gap | Widens, Narrows, No clear effect, or Indirect |
| Key Sources | Linked to the Source record created in the same run |

---

## Error Handling

- **Paywalled or JS-rendered pages**: scraping will fail with a clear message. Use `--text` and paste the article content manually.
- **Malformed Claude responses**: the agent retries once with a stricter prompt before exiting.
- **Invalid enum values**: defaulted to `Other` with a warning printed to the console.
- **Notion API errors**: the full error response is printed — nothing fails silently.

---

## Project Structure

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
