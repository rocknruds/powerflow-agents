# PowerFlow Agents

> *Intelligence systems reveal what declarations conceal.*

PowerFlow is a geopolitical intelligence platform built on a single premise: the gap between claimed authority and exercised control is where the real story lives. This repo contains the **agent layer** — the Python pipeline that ingests raw intelligence, extracts structured data, scores actors, and writes everything into the PowerFlow knowledge graph.

---

## What PowerFlow Actually Does

Most geopolitical analysis describes what actors *say* they control. PowerFlow measures what they *actually* control — and tracks how that changes over time.

The core analytical unit is the **PF Score** (0–100): a weighted composite of two dimensions assessed for every actor in the system.

| Dimension | What It Measures | Weight |
|---|---|---|
| **Authority Score** | Real internal control within claimed territory or domain | 60% |
| **Reach Score** | External influence — ability to shape outcomes beyond own borders | 40% |
| **PF Score** | Composite measure of real-world power | — |

The system tracks ~35+ actors across state, non-state, hybrid, and IGO categories. Scores are calibrated against a seven-tier anchor system — from the US and China (PF 80–90) down to collapsed states (PF 3–10) — with patron ceiling rules (proxies cannot outscore sponsors) and peer context injection to prevent calibration drift.

### Why This Is Hard to Replicate

Three things make PowerFlow's scores defensible rather than just decorative:

1. **Structured ingestion with editorial control.** Every piece of source material passes through a relevance screener (0–100 score across five analytical dimensions) before extraction. Paywalled analytical sources are ingested manually — by design. Data quality is a feature.

2. **Score coherence architecture.** Scoring uses anchor actors, peer comparison context, and a full-registry recalibration sweep with analyst approval gates. The system is designed so scores mean something *relative to each other*, not just in isolation.

3. **Living knowledge graph.** The Notion backend isn't a database of static facts. It's a relational system where actors, events, conflicts, scenarios, and intelligence feeds connect to each other — and where scores update as ground truth shifts.

---

## System Architecture

```
Source Material (articles, reports, PDFs)
        ↓
   Relevance Screener (Claude, 0–100 score)
        ↓
   Extractor Agent (Claude Sonnet)
        ↓ ↓ ↓ ↓
Actors  Events  Intel Feeds  Sources   ← Notion databases
   ↓
Score Agent (Claude Sonnet + anchor context)
        ↓
Score Snapshots + Actor Registry update
```

**Streamlit interface** (`app.py`) provides the operational control layer: ingestion UI, scoring interface, brief generation, and full-registry rescore with approval gates.

**Notion backend** serves as the analytical brain: a relational knowledge graph with interconnected databases for Actors, Events, Conflicts, Scenarios, Briefs, and more.

**Next.js frontend** (`rocknruds/powerflow-app`) is the public-facing interface — currently in development, deprioritized until data quality is production-ready.

---

## Agents

### Ingestion Agent (`agents/ingest/`)

Accepts a URL or pasted article text. Runs it through:

1. **Relevance screener** — scores the piece 0–100 across five analytical dimensions. Low-relevance content is flagged before extraction.
2. **Extractor** — Claude Sonnet extracts structured geopolitical data and writes simultaneously to four Notion databases: Sources, Events Timeline, Intelligence Feeds, and Actors Registry.

Actor deduplication and institutional fragment filtering are built in — military commands, government departments, and sub-units are not created as standalone actors.

### Score Agent (`score.py`)

Scores any actor in the registry using:
- Seven-tier anchor reference table for calibration
- Peer context injection (similar actors compared at scoring time)
- Patron ceiling rules (proxies capped relative to sponsors)
- Claude Sonnet for reasoning quality

Writes Authority Score, Reach Score, PF Score, and analytical rationale to the Actor page and creates a Score Snapshot for longitudinal tracking.

### Rescore Registry (Streamlit Page 5)

Full-registry sweep with analyst approval gates. Rescores all actors, displays results in a comparison table with reasoning, and requires manual approval before writing to Notion. Designed to catch and correct calibration drift before it compounds.

---

## Setup

### Prerequisites

- Python 3.11+
- An Anthropic API key ([console.anthropic.com](https://console.anthropic.com))
- A Notion integration token with access to the PowerFlow workspace

### Install

```bash
git clone https://github.com/rocknruds/powerflow-agents
cd powerflow-agents
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Configure

```bash
cp .env.example .env
```

Edit `.env`:

```
ANTHROPIC_API_KEY=your_anthropic_api_key
NOTION_API_KEY=your_notion_integration_token
```

### Run

```bash
# Launch the full Streamlit interface
streamlit run app.py

# Or run the ingestion agent directly
python -m agents.ingest.run --url "https://example.com/article"
python -m agents.ingest.run --text "Paste article text here..."
```

---

## Using with Claude Code

This repo is designed to be worked on with [Claude Code](https://claude.ai/code) — Anthropic's agentic coding tool that reads your codebase directly and makes coordinated changes across multiple files.

### Install Claude Code

**macOS / Linux:**
```bash
curl -fsSL https://claude.ai/install.sh | bash
```

**Windows (PowerShell):**
```powershell
irm https://claude.ai/install.ps1 | iex
```

Requires a paid Claude account (Pro, Max, Teams, or Enterprise). No Node.js required for the native installer.

### Run Claude Code in this repo

```bash
cd powerflow-agents
claude
```

Claude Code will read `CLAUDE.md` at startup for project context. A `CLAUDE.md` file is included in this repo — see it for the current system state, active work, and key architectural decisions.

---

## Project Structure

```
powerflow-agents/
├── agents/
│   └── ingest/
│       ├── scraper.py        # URL fetching and text cleaning
│       ├── extractor.py      # LLM extraction (Anthropic SDK)
│       ├── notion_writer.py  # Notion API writes
│       └── run.py            # CLI entrypoint
├── config/
│   └── settings.py           # Env vars, constants, model config
├── pages/                    # Streamlit multi-page app
├── score.py                  # Score agent
├── app.py                    # Streamlit entrypoint
├── CLAUDE.md                 # Claude Code context file
├── .env.example
└── requirements.txt
```

---

## Notion Database IDs

| Database | ID |
|---|---|
| Actors Registry | `7aa6bbc818ad4a35a4059fbe2537d115` |
| Events Timeline | `70e9768bfcec49a9aa8565d5aa1f1881` |
| Intelligence Feeds | `3835cb822ae441a5a18cb4271d9fe955` |
| Score Snapshots | `e96696510cac4435a52e89be9fb6a969` |
| Scenarios | `430eb13962d44154b9761785faf01300` |
| Briefs | `df4e70c01fa1460d8f9bb6c26f05dc1a` |

---

## Error Handling

- **Paywalled or JS-rendered pages**: scraper will fail cleanly. Use `--text` and paste content manually — this is intentional, not a limitation.
- **Low relevance scores**: the screener will flag and optionally abort before extraction.
- **Notion API errors**: nothing fails silently. Full error responses are printed to console.
- **Score calibration issues**: use the Rescore Registry page (Page 5) to run a full sweep with manual approval before writing.
