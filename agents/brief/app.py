"""PowerFlow — Weekly Brief Generator.

Streamlit UI for the briefing agent. Fetches recent Notion data, collects an
editorial priority from the analyst, sends everything to Claude for synthesis,
and writes the approved brief back to Notion.

Run from the repo root:
    streamlit run agents/brief/app.py
"""

from __future__ import annotations

import datetime
import sys
from pathlib import Path

# Ensure the repo root is on the path so config.settings resolves correctly
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import streamlit as st

from agents.brief import fetcher, writer

# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="PowerFlow — Weekly Brief Generator",
    page_icon="📋",
    layout="wide",
)

st.title("📋 PowerFlow — Weekly Brief Generator")
st.caption("Synthesize a structured intelligence brief from recent Notion data.")

# ── Session state init ────────────────────────────────────────────────────────

if "data" not in st.session_state:
    st.session_state.data = None
if "brief_text" not in st.session_state:
    st.session_state.brief_text = None
if "saved_url" not in st.session_state:
    st.session_state.saved_url = None


# ── Data fetch ────────────────────────────────────────────────────────────────

@st.cache_data(ttl=300, show_spinner=False)
def load_data(lookback_days: int = 7) -> dict:
    return fetcher.fetch_all(lookback_days=lookback_days)


with st.sidebar:
    st.header("Settings")
    lookback = st.number_input(
        "Lookback window (days)",
        min_value=1,
        max_value=90,
        value=7,
        step=1,
        help="Set to 30 for a monthly brief.",
    )
    if st.button("🔄 Refresh data"):
        st.cache_data.clear()
        st.session_state.data = None
        st.session_state.brief_text = None
        st.session_state.saved_url = None
        st.rerun()

# Load data (cached)
if st.session_state.data is None:
    with st.spinner("Fetching data from Notion…"):
        try:
            st.session_state.data = load_data(lookback_days=int(lookback))
        except Exception as exc:
            st.error(f"Failed to fetch Notion data: {exc}")
            st.stop()

data: dict = st.session_state.data
events = data.get("events", [])
feeds = data.get("intel_feeds", [])
snapshots = data.get("score_snapshots", [])
scenarios = data.get("active_scenarios", [])
date_range = data.get("date_range", "")

# ── Data summary panel ────────────────────────────────────────────────────────

st.markdown("---")
col1, col2, col3, col4 = st.columns(4)
col1.metric("Events", len(events))
col2.metric("Intel Feeds", len(feeds))
col3.metric("Score Movers", len(snapshots))
col4.metric("Active Scenarios", len(scenarios))

st.info(
    f"📊 Found: **{len(events)}** events · **{len(feeds)}** intel feeds · "
    f"**{len(snapshots)}** score movers · **{len(scenarios)}** active scenarios"
)

# ── Collapsible raw data expanders ────────────────────────────────────────────

with st.expander(f"📅 Events ({len(events)})", expanded=False):
    if events:
        for e in events:
            st.markdown(
                f"**{e.get('name', 'Unnamed')}** "
                f"— {e.get('event_type', '')} "
                f"| {e.get('date', '')} "
                f"| PF Signal: {e.get('pf_signal', 'n/a')}"
            )
            if e.get("description"):
                st.caption(e["description"])
    else:
        st.write("No events found in this window.")

with st.expander(f"🔍 Intelligence Feeds ({len(feeds)})", expanded=False):
    if feeds:
        for f in feeds:
            st.markdown(
                f"**{f.get('name', 'Unnamed')}** — {f.get('confidence_shift', '')}"
            )
            if f.get("so_what_summary"):
                st.caption(f["so_what_summary"])
    else:
        st.write("No intel feeds found in this window.")

with st.expander(f"📈 Score Movers ({len(snapshots)})", expanded=False):
    if snapshots:
        for s in snapshots:
            actor = s.get("actor") or s.get("title") or "Unknown"
            delta = s.get("score_delta")
            score = s.get("score")
            delta_str = f"{delta:+.0f}" if delta is not None else "n/a"
            score_str = f"{score:.0f}" if score is not None else "n/a"
            st.markdown(f"**{actor}** — Score: {score_str} (Δ {delta_str})")
            if s.get("trigger_notes"):
                st.caption(s["trigger_notes"])
    else:
        st.write("No score movers found in this window.")

with st.expander(f"⚠️ Active Scenarios ({len(scenarios)})", expanded=False):
    if scenarios:
        for sc in scenarios:
            st.markdown(
                f"**{sc.get('name', 'Unnamed')}** "
                f"[{sc.get('scenario_class', '')}] "
                f"| p={sc.get('probability_estimate', 'n/a')}"
            )
            if sc.get("trigger_condition"):
                st.caption(f"Trigger: {sc['trigger_condition']}")
    else:
        st.write("No active scenarios found.")

# ── Brief generation form ─────────────────────────────────────────────────────

st.markdown("---")
st.subheader(f"📆 Date Range: {date_range}")

focus_options = [
    "US-Iran War & Operation Epic Fury",
    "Strait of Hormuz & Global Oil Shock",
    "Gulf State Sovereignty Exposure",
    "Iran Regime Survival & Transition",
    "Houthi Reactivation & Red Sea",
    "Russia-Ukraine & NATO Posture",
    "China-Taiwan & Indo-Pacific",
    "Pakistan-Afghanistan Escalation",
    "Venezuela Post-Maduro Transition",
    "Cuba Economic Collapse",
    "DRC & Central Africa",
    "Nuclear Proliferation Cascade",
    "US De-institutionalization & Foreign Policy",
    "Gulf Alliance Fractures (Saudi-UAE)",
]

selected_focus = st.multiselect(
    "Quick focus — select areas to emphasize (optional):",
    options=focus_options,
)

priority_text = st.text_area(
    "Additional context or nuance (optional):",
    placeholder="e.g. Focus on second-order effects, ignore Venezuela",
    height=100,
)

# Combine into the priority string passed to generate_brief
if selected_focus and priority_text.strip():
    priority = f"FOCUS AREAS: {', '.join(selected_focus)}\n\n{priority_text.strip()}"
elif selected_focus:
    priority = f"FOCUS AREAS: {', '.join(selected_focus)}"
else:
    priority = priority_text.strip()

generate_btn = st.button("⚡ Generate Brief", type="primary", use_container_width=True)

if generate_btn:
    st.session_state.brief_text = None
    st.session_state.saved_url = None
    with st.spinner("Synthesizing brief…"):
        try:
            st.session_state.brief_text = writer.generate_brief(data, priority)
        except Exception as exc:
            st.error(f"Brief generation failed: {exc}")

# ── Brief preview & approval ──────────────────────────────────────────────────

if st.session_state.brief_text:
    st.markdown("---")
    st.subheader("📄 Generated Brief")

    st.markdown(st.session_state.brief_text)

    st.markdown(" ")
    col_approve, col_regen = st.columns(2)

    with col_approve:
        approve_btn = st.button(
            "✅ Approve & Save to Notion",
            type="primary",
            use_container_width=True,
            disabled=bool(st.session_state.saved_url),
        )

    with col_regen:
        regen_btn = st.button(
            "🔁 Regenerate",
            use_container_width=True,
        )

    if regen_btn:
        st.session_state.brief_text = None
        st.session_state.saved_url = None
        with st.spinner("Synthesizing brief…"):
            try:
                st.session_state.brief_text = writer.generate_brief(data, priority)
                st.rerun()
            except Exception as exc:
                st.error(f"Brief generation failed: {exc}")

    if approve_btn:
        # Calculate date_range_start for the Notion property
        start_dt = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
            days=int(lookback)
        )
        date_range_start = start_dt.date().isoformat()

        with st.spinner("Saving to Notion…"):
            try:
                page_id, page_url = writer.save_brief(
                    brief_text=st.session_state.brief_text,
                    date_range=date_range,
                    priority=priority,
                    date_range_start=date_range_start,
                )
                st.session_state.saved_url = page_url
                writer.log_brief_activity(status="Completed")
            except Exception as exc:
                writer.log_brief_activity(status="Failed", notes=str(exc))
                st.error(f"Failed to save brief to Notion: {exc}")

    if st.session_state.saved_url:
        st.success(
            f"✅ Brief saved to Notion! [Open page →]({st.session_state.saved_url})"
        )
