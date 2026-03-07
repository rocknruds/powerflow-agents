import os
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
NOTION_API_KEY = os.environ["NOTION_API_KEY"]

# Notion database IDs (collection IDs)
NOTION_EVENTS_DB_ID = os.environ["NOTION_EVENTS_DB_ID"]
NOTION_SOURCES_DB_ID = os.environ["NOTION_SOURCES_DB_ID"]
NOTION_INTEL_FEEDS_DB_ID = os.environ["NOTION_INTEL_FEEDS_DB_ID"]
NOTION_ACTORS_DB_ID = os.environ.get("NOTION_ACTORS_DB_ID", "742dea54-b13e-4c64-81b7-2c058483de4e")
NOTION_INDIVIDUALS_DB_ID = "4f8874fdda8548f0a7a6dc560f4ddfcd"
NOTION_ACTIVITY_LOG_DB_ID = os.environ.get("NOTION_ACTIVITY_LOG_DB_ID", "d4e38407c7914f3ba3b401d8bd492ce1")

# Briefing agent — set once the Briefs database is created in Notion
BRIEFS_DB_ID = os.environ.get("BRIEFS_DB_ID", "df4e70c01fa1460d8f9bb6c26f05dc1a")

# Recalibration agent — Actors Registry, Score Snapshots, Activity Log (same Activity Log as ingestion)
NOTION_SCORE_SNAPSHOTS_DB_ID = os.environ.get(
    "NOTION_SCORE_SNAPSHOTS_DB_ID", "e96696510cac4435a52e89be9fb6a969"
)

# Claude model settings
CLAUDE_MODEL = "claude-sonnet-4-6"
CLAUDE_MAX_TOKENS = 2048

# Score Agent settings
CLAUDE_SCORE_MODEL = os.getenv("CLAUDE_SCORE_MODEL", "claude-sonnet-4-6")
CLAUDE_SCORE_MAX_TOKENS = 768  # scores are small JSON objects

# Valid enum values for validation
VALID_SOURCE_TYPES = {
    "Academic",
    "Analytical / Longform",
    "Government",
    "News",
    "Think tank",
    "OSINT",
    "Legal document",
    "Other",
}

VALID_RELIABILITY = {"High", "Medium", "Low"}

VALID_EVENT_TYPES = {
    "Legal change",
    "Military or coercive action",
    "Sanctions or economic measure",
    "Institutional reform",
    "Alliance or treaty shift",
    "Information-cyber",
    "Other",
}

# PF Signal: direction of power gap movement — use Notion-native select values directly.
# Widening = actor loses effective control/influence (gap expands)
# Narrowing = actor consolidates control/gains influence (gap shrinks)
# Mixed     = different actors move in opposite directions within the same event
# Stable    = no meaningful score movement expected
# Unclear   = genuinely insufficient information (last resort only)
VALID_PF_SIGNAL_IMPACTS = {
    "Widening",
    "Narrowing",
    "Mixed",
    "Stable",
    "Unclear",
}

VALID_ACTOR_TYPES = {
    "State",
    "Non-State",
    "Hybrid",
    "IGO",
    "Individual",
}

# Maps LLM-returned actor types to exact Notion select option names
ACTOR_TYPE_NOTION_MAP: dict[str, str] = {
    "IGO": "International Organization",
}
