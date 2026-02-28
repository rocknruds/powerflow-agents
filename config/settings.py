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
NOTION_ACTIVITY_LOG_DB_ID = os.environ.get("NOTION_ACTIVITY_LOG_DB_ID", "d4e38407c7914f3ba3b401d8bd492ce1")

# Claude model settings
CLAUDE_MODEL = "claude-haiku-4-5-20251001"
CLAUDE_MAX_TOKENS = 2048

# Score Agent settings
CLAUDE_SCORE_MODEL = os.getenv("CLAUDE_SCORE_MODEL", CLAUDE_MODEL)  # defaults to Haiku
CLAUDE_SCORE_MAX_TOKENS = 512  # scores are small JSON objects

# Valid enum values for validation
VALID_SOURCE_TYPES = {
    "Academic",
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

# PF Signal: does this event widen or narrow the gap between an actor's claimed
# authority and actual control (i.e. does it hurt or help their Authority Score)?
VALID_PF_SIGNAL_IMPACTS = {
    "Widens",
    "Narrows",
    "No clear effect",
    "Indirect",
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
