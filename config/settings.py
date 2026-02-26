import os
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
NOTION_API_KEY = os.environ["NOTION_API_KEY"]

# Notion database IDs (collection IDs)
NOTION_EVENTS_DB_ID = "21452f2f-6f38-4a70-8f3b-dabbb7ee81f1"
NOTION_SOURCES_DB_ID = "c0e5c418-893f-4138-bc0d-7d046b02323d"

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
