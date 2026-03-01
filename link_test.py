from agents.ingest.conflict_matcher import run_conflict_matching

run_conflict_matching(
    "314f8ae9-4162-819a-94b5-cad0f6dccdad",
    {
        "event_name": "Pakistan Declares Open War With Taliban Afghanistan",
        "description": "Pakistan escalates military operations against Taliban-controlled Afghanistan following cross-border attacks by TTP militants.",
        "event_type": "Military or coercive action"
    },
    [
        {"name": "Pakistan"},
        {"name": "Afghanistan (Taliban)"},
        {"name": "Tehreek-e-Taliban Pakistan (TTP)"}
    ]
)