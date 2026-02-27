import os
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
NOTION_API_KEY = os.environ["NOTION_API_KEY"]

# Notion database IDs (collection IDs)
NOTION_EVENTS_DB_ID = "70e9768bfcec49a9aa8565d5aa1f1881"
NOTION_SOURCES_DB_ID = "0c3415c21d944845841665bdcd1c529e"

# Claude model settings
CLAUDE_MODEL = "claude-haiku-4-5-20251001"
CLAUDE_MAX_TOKENS = 1024

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

VALID_SOVEREIGNTY_IMPACTS = {
    "Widens",
    "Narrows",
    "No clear effect",
    "Indirect",
}
