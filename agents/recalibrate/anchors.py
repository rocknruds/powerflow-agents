"""Tiered anchor actors for PowerFlow recalibration. Locked reference points — never adjusted by the agent."""

ANCHOR_ACTORS = {
    # Tier 1 — Top (80–90)
    "United States": {
        "authority": 85,
        "reach": 88,
        "pf_score": 86,
        "tier": "Top",
        "rationale": "Deepest institutional depth on earth, unmatched global force projection across all domains",
    },
    "China": {
        "authority": 82,
        "reach": 75,
        "pf_score": 79,
        "tier": "Top",
        "rationale": "Near-total internal control, massive and growing external reach but still regionally concentrated",
    },
    # Tier 2 — High (65–78)
    "Russia": {
        "authority": 74,
        "reach": 68,
        "pf_score": 71,
        "tier": "High",
        "rationale": "Strong internal consolidation under Putin, significant but degraded external reach post-Ukraine",
    },
    "United Kingdom": {
        "authority": 78,
        "reach": 65,
        "pf_score": 73,
        "tier": "High",
        "rationale": "Stable democratic authority, global reach diminished post-empire but still substantial via Five Eyes and NATO",
    },
    "France": {
        "authority": 76,
        "reach": 63,
        "pf_score": 71,
        "tier": "High",
        "rationale": "Strong state authority, meaningful external reach particularly in Francophone Africa and EU leadership",
    },
    "Germany": {
        "authority": 79,
        "reach": 58,
        "pf_score": 72,
        "tier": "High",
        "rationale": "Highest institutional authority in Europe, reach constrained by post-WWII doctrine and limited hard power",
    },
    # Tier 3 — Mid-High (52–65)
    "Israel": {
        "authority": 72,
        "reach": 68,
        "pf_score": 70,
        "tier": "Mid-High",
        "rationale": "Strong internal control, outsized external reach relative to size via intelligence and military operations",
    },
    "Turkey": {
        "authority": 65,
        "reach": 58,
        "pf_score": 62,
        "tier": "Mid-High",
        "rationale": "Consolidated Erdogan authority, active external projection in Syria, Libya, Azerbaijan, and Caucasus",
    },
    "India": {
        "authority": 68,
        "reach": 52,
        "pf_score": 62,
        "tier": "Mid-High",
        "rationale": "Strong democratic authority, growing regional reach but still primarily continental in projection",
    },
    # Tier 4 — Mid (38–52)
    "Saudi Arabia": {
        "authority": 58,
        "reach": 52,
        "pf_score": 56,
        "tier": "Mid",
        "rationale": "Consolidating MBS authority internally, significant but patron-dependent external reach via petrodollar influence",
    },
    "Iran (2023 baseline)": {
        "authority": 52,
        "reach": 48,
        "pf_score": 50,
        "tier": "Mid",
        "rationale": "Pre-Epic Fury baseline — functional theocratic authority, substantial proxy network reach across the region",
    },
    # Tier 5 — Mid-Low (28–38)
    "Hezbollah (pre-2024 baseline)": {
        "authority": 48,
        "reach": 42,
        "pf_score": 46,
        "tier": "Mid-Low",
        "rationale": "Pre-degradation baseline — near-state parallel authority in southern Lebanon, meaningful regional reach via Iran axis",
    },
    # Tier 6 — Low (12–22)
    "Hamas (post-Oct 7)": {
        "authority": 18,
        "reach": 12,
        "pf_score": 16,
        "tier": "Low",
        "rationale": "Near-destroyed organizationally, governance in Gaza collapsed, external reach minimal and dependent on Iran lifeline",
    },
    # Tier 7 — Floor (3–10)
    "Yemen (Houthi-controlled)": {
        "authority": 12,
        "reach": 8,
        "pf_score": 10,
        "tier": "Floor",
        "rationale": "Fragmented failed state, Houthi de facto control is localized and contested, reach limited to Red Sea disruption",
    },
}


def is_anchor_actor(name: str) -> bool:
    """True if name matches an anchor key (exact match). Live registry names like 'Hezbollah' are not anchor keys; 'Hezbollah (pre-2024 baseline)' is."""
    return name.strip() in ANCHOR_ACTORS


def get_anchor_names() -> set[str]:
    """Set of all anchor display names (keys). Used to exclude from adjustment list and to detect mistaken adjustments."""
    return set(ANCHOR_ACTORS.keys())
