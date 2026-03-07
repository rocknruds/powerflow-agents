# PowerFlow Agents — Claude Code Context

## What This System Is

PowerFlow is a geopolitical intelligence platform that tracks how power actually moves through the world by quantifying the gap between claimed authority and exercised control. This repo is the **agent pipeline** — it ingests source material, extracts structured data, scores actors, and writes everything into the Notion-based knowledge graph.

The system is intentionally **data-quality-first**. The public frontend exists but is deprioritized. What matters right now is coherent, defensible scores and a clean, well-structured knowledge graph.

---

## Core Analytical Model

Every actor has a **PF Score** (0–100):
- **Authority Score** — real internal control within claimed territory (60% weight)
- **Reach Score** — external influence projection (40% weight)
- **PF Score** = Authority × 0.6 + Reach × 0.4

Scores use a **seven-tier anchor system** for calibration:
- US / China: PF 80–90
- Russia / EU: PF 60–75
- Regional powers (Iran, Saudi, Turkey): PF 40–60
- Mid-tier actors: PF 25–40
- Weak states / significant non-state actors: PF 15–25
- Fragmented actors: PF 8–15
- Collapsed / symbolic actors (Yemen): PF 3–10

**Patron ceiling rule**: proxy actors cannot outscore their sponsors.

**Score coherence is the core value proposition.** Incoherent relative scores compound with data volume and undermine everything. Calibration infrastructure takes priority over ingestion scaling.

---

## Key Architecture Decisions

- **Manual ingestion is intentional** — paywalled analytical sources are the signal, not a limitation
- **Institutional fragments are not standalone actors** — military commands, government departments, agencies belong to their parent state actor, not as separate registry entries
- **Individuals (heads of state, key figures) route to Influential Individuals DB**, not Actors Registry
- **All other actors go to Actors Registry** with appropriate Actor Type
- **Visibility flags** (Public/Internal) and **Status flags** (Active/Superseded/Archived) manage content lifecycle — nothing gets deleted
- **Score Snapshots** are append-only — every scoring run creates a new snapshot for longitudinal tracking
- **Prompt caching** is implemented on static system prompts in the screener and extractor

---

## Notion Backend

The Notion workspace is the analytical brain. All databases are relational.

**Key database IDs:**
```
Actors Registry:      7aa6bbc818ad4a35a4059fbe2537d115
Events Timeline:      70e9768bfcec49a9aa8565d5aa1f1881
Intelligence Feeds:   3835cb822ae441a5a18cb4271d9fe955
Score Snapshots:      e96696510cac4435a52e89be9fb6a969
Scenarios:            430eb13962d44154b9761785faf01300
Briefs:               df4e70c01fa1460d8f9bb6c26f05dc1a
Expansion Log:        312f8ae94162819e8cfbc45559703d9f
```

**Key actor page IDs (anchors):**
```
United States:  315f8ae9416281879bb9efddcfb4761f
China:          313f8ae9416281b7a84aec5fdb8a89ab
Russia:         314f8ae9416281d2bcf0c1a90fdbfdfa
```

**Notion collection ID** (for search): `742dea54-b13e-4c64-81b7-2c058483de4e`

---

## Model Configuration

| Use Case | Model |
|---|---|
| Screening & extraction | `claude-haiku-4-5-20251001` |
| Scoring | `claude-sonnet-4-6` |
| Brief generation | Claude Opus (via API, not this repo) |

Scoring max tokens: 768 (scores are small JSON objects).
Extraction max tokens: 2048.

---

## Current State & Active Work

### What's Working
- Full ingestion pipeline (URL + text input)
- Relevance screener (0–100, five dimensions)
- Extractor writing to four Notion databases simultaneously
- Actor deduplication (blocks institutional fragments)
- Individual actor routing to Influential Individuals DB
- Intel Feed relational fields (Actors Involved, Source, Linked Records)
- Score agent with anchor context + peer context + patron ceiling
- Streamlit multi-page app (Pages 1–5)
- Rescore Registry (Page 5) — full sweep with approval gates

### Known Issues / Active
- **Score calibration drift** — identified post-Operation Epic Fury. The recalibration agent (Page 5) exists to address this; run it before scaling ingestion.
- **Data cleanup pass** — pre-fix ingestion entries need backfill for some fields; some duplicate test entries exist
- **Author normalization** — Author field on Sources not always consistent
- **PDF support** — scraper handles PDFs but reliability varies
- **URL scraper timeouts** — some sources time out; use `--text` mode as fallback

### On The Horizon
- Activity logging for agent runs (currently missing)
- Migrating text cross-references to formal Notion RELATION fields
- Deduplication check on re-ingestion (prevent duplicate entries)
- Next.js frontend (deprioritized; repo: `rocknruds/powerflow-app`)

---

## Repo Structure

```
powerflow-agents/
├── agents/
│   └── ingest/
│       ├── scraper.py        # URL fetching and text cleaning
│       ├── extractor.py      # LLM extraction (Anthropic SDK)
│       ├── notion_writer.py  # Notion API writes (4 databases)
│       └── run.py            # CLI entrypoint
├── config/
│   └── settings.py           # Env vars, constants, valid enums, model config
├── pages/                    # Streamlit multi-page app pages
├── score.py                  # Score agent (anchor + peer context + ceiling rules)
├── app.py                    # Streamlit entrypoint
├── requirements.txt
└── .env.example
```

---

## Working Conventions

- **Never create standalone actors for institutional sub-units** (e.g. "US Central Command", "IRGC Quds Force" as top-level actors). They are organs of parent state actors.
- **Always check for actor duplicates** before creating new Actors Registry entries.
- **Score coherence check**: after any scoring changes, verify that relative scores make sense across the anchor tier system — US/China should not score below major regional powers, proxies should not outscore sponsors.
- **Log significant changes** in the Expansion Log (Notion DB ID above) using toggle sections by date with ADDED / FIXED / DEFERRED / NEXT structure.
- **Visibility = Internal** for anything not ready for public-facing display. Do not delete.
- When uncertain about Notion field names, query the database first rather than guessing.

---

## Environment Variables

```
ANTHROPIC_API_KEY=       # Anthropic API key
NOTION_API_KEY=          # Notion integration token
NOTION_ACTORS_DB_ID=     # 7aa6bbc818ad4a35a4059fbe2537d115
NOTION_EVENTS_DB_ID=     # 70e9768bfcec49a9aa8565d5aa1f1881
NOTION_INTEL_FEEDS_DB_ID= # 3835cb822ae441a5a18cb4271d9fe955
NOTION_SOURCES_DB_ID=    # (check settings.py for current value)
NOTION_SCORE_SNAPSHOTS_DB_ID= # e96696510cac4435a52e89be9fb6a969
CLAUDE_MODEL=            # claude-haiku-4-5-20251001 (default for extraction)
CLAUDE_SCORE_MODEL=      # claude-sonnet-4-6 (scoring)
```
## Running the app
Always use `streamlit run app.py` from the repo root. Never run `agents/brief/app.py` directly.