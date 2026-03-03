"""PowerFlow — Rescore Registry.

Fetches all actors from the Actors Registry and rescores them using the
Score Agent (Sonnet + anchor calibration + peer context). Displays a live
summary table with before/after scores and ceiling flags.
"""

from __future__ import annotations

import sys
from pathlib import Path

import requests
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import NOTION_API_KEY
from agents.score.score_agent import score_actors

ACTORS_DB_ID = "7aa6bbc818ad4a35a4059fbe2537d115"

# ── Session state ─────────────────────────────────────────────────────────────

def _init():
    if "rescore_results" not in st.session_state:
        st.session_state.rescore_results = None
    if "rescore_actor_ids" not in st.session_state:
        st.session_state.rescore_actor_ids = None
    if "rescore_running" not in st.session_state:
        st.session_state.rescore_running = False

def _reset():
    st.session_state.rescore_results = None
    st.session_state.rescore_actor_ids = None
    st.session_state.rescore_running = False

# ── Notion fetch ──────────────────────────────────────────────────────────────

def fetch_all_actors() -> list[dict]:
    """Fetch all actor IDs and names from the Actors Registry."""
    url = f"https://api.notion.com/v1/databases/{ACTORS_DB_ID}/query"
    headers = {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28",
    }
    actors = []
    start_cursor = None

    while True:
        payload = {}
        if start_cursor:
            payload["start_cursor"] = start_cursor
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        for page in data.get("results", []):
            props = page.get("properties", {})
            name_items = props.get("Name", {}).get("title", [])
            name = "".join(i.get("plain_text", "") for i in name_items).strip()
            if name:
                actors.append({"id": page["id"], "name": name})
        if data.get("has_more") and data.get("next_cursor"):
            start_cursor = data["next_cursor"]
        else:
            break

    return actors

# ── Page ──────────────────────────────────────────────────────────────────────

st.markdown("## 🔁 Rescore Registry")
st.markdown(
    "Rescore all actors in the Actors Registry using the calibrated Score Agent "
    "(Sonnet + anchor reference + peer context). Writes updated scores and new "
    "Score Snapshots to Notion for any actor whose score changes."
)
st.divider()

_init()

# ── Fetch actor count preview ─────────────────────────────────────────────────

if st.session_state.rescore_actor_ids is None:
    try:
        actors = fetch_all_actors()
        st.session_state.rescore_actor_ids = actors
    except Exception as e:
        st.error(f"Failed to fetch actors: {e}")
        st.stop()

actors = st.session_state.rescore_actor_ids
st.info(f"**{len(actors)}** actors in registry. Each will be rescored sequentially.")

with st.expander("View actors to be rescored", expanded=False):
    for a in actors:
        st.markdown(f"- {a['name']}")

st.divider()

# ── Controls ──────────────────────────────────────────────────────────────────

col_run, col_reset = st.columns([3, 1])

with col_run:
    run_btn = st.button(
        "🔁 Rescore All Actors",
        type="primary",
        use_container_width=True,
        disabled=bool(st.session_state.rescore_results),
    )

with col_reset:
    if st.button("🔄 Reset", use_container_width=True):
        _reset()
        st.rerun()

# ── Run rescore ───────────────────────────────────────────────────────────────

if run_btn:
    actor_ids = [a["id"] for a in actors]
    with st.spinner(f"Rescoring {len(actor_ids)} actors — this may take a few minutes…"):
        try:
            results = score_actors(actor_ids)
            st.session_state.rescore_results = results
        except Exception as e:
            st.error(f"Rescore failed: {e}")

# ── Results ───────────────────────────────────────────────────────────────────

if st.session_state.rescore_results:
    results = st.session_state.rescore_results
    succeeded = [r for r in results if r["success"]]
    failed = [r for r in results if not r["success"]]
    ceilings = [r for r in results if r.get("ceiling_applied")]

    st.markdown("---")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total", len(results))
    col2.metric("Succeeded", len(succeeded))
    col3.metric("Ceiling Applied", len(ceilings))
    col4.metric("Failed", len(failed))

    st.markdown("### Results")

    # Build display table
    import pandas as pd

    rows = []
    for r in succeeded:
        old_pf = r.get("old_pf_score")
        new_pf = r["pf_score"]
        delta = round(new_pf - old_pf, 1) if old_pf is not None else None
        rows.append({
            "Actor": r["actor_name"],
            "Authority": r["authority_score"],
            "Reach": r["reach_score"],
            "PF Score": round(new_pf, 1),
            "Δ PF": f"{delta:+.1f}" if delta is not None else "first score",
            "Ceiling": "Yes" if r.get("ceiling_applied") else "",
        })

    df = pd.DataFrame(rows).sort_values("PF Score", ascending=False)

    def _highlight(row):
        if row["Ceiling"] == "Yes":
            return ["background-color: #fef3c722;"] * len(row)
        return [""] * len(row)

    st.dataframe(
        df.style.apply(_highlight, axis=1),
        use_container_width=True,
        hide_index=True,
    )

    # Reasoning expander per actor
    st.markdown("### Reasoning")
    for r in succeeded:
        with st.expander(f"{r['actor_name']} — PF {r['pf_score']:.0f}", expanded=False):
            st.markdown(f"**Authority:** {r['authority_score']} | **Reach:** {r['reach_score']}")
            if r.get("ceiling_applied"):
                st.warning("Patron ceiling was applied to Reach Score.")
            st.markdown(r.get("reasoning", "No reasoning returned."))

    if failed:
        st.markdown("### Failed")
        for r in failed:
            st.error(f"**{r['actor_name']}** — {r['error']}")
