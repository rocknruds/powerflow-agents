"""PowerFlow Recalibration — evaluate actor score registry against tiered anchors and approve adjustments."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

# Ensure repo root is on sys.path for agents/config
sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.recalibrate.anchors import get_anchor_names
from agents.recalibrate.recalibrate import (
    fetch_full_registry,
    run_calibration_pass,
    validate_adjustments,
    write_approved_changes,
)

# ── Session state keys ────────────────────────────────────────────────────────

def _recal_init():
    if "recal_registry" not in st.session_state:
        st.session_state.recal_registry = None
    if "recal_valid" not in st.session_state:
        st.session_state.recal_valid = []
    if "recal_invalid_reasons" not in st.session_state:
        st.session_state.recal_invalid_reasons = []
    if "recal_distribution_notes" not in st.session_state:
        st.session_state.recal_distribution_notes = ""
    if "recal_approved" not in st.session_state:
        st.session_state.recal_approved = set()  # indices into recal_valid
    if "recal_written" not in st.session_state:
        st.session_state.recal_written = None  # after write: (written_names, activity_page_id)
    if "recal_error" not in st.session_state:
        st.session_state.recal_error = None


def _recal_reset_after_run():
    st.session_state.recal_valid = []
    st.session_state.recal_invalid_reasons = []
    st.session_state.recal_distribution_notes = ""
    st.session_state.recal_approved = set()
    st.session_state.recal_written = None
    st.session_state.recal_error = None


# ── Header ────────────────────────────────────────────────────────────────────

st.markdown("## 🎯 Recalibrate Scores")
st.markdown(
    "Evaluate the full PowerFlow actor registry against tiered anchor reference points. "
    "Review proposed adjustments and approve changes to write to the Actors Registry, Score Snapshots, and Activity Log."
)
st.divider()

_recal_init()
anchor_names = get_anchor_names()

# ── Run calibration ──────────────────────────────────────────────────────────

run_clicked = st.button("🔄 Run calibration pass", type="primary", help="Fetch registry, run Claude, validate output.")

if run_clicked:
    _recal_reset_after_run()
    with st.spinner("Fetching full actor registry…"):
        try:
            registry = fetch_full_registry()
            st.session_state.recal_registry = registry
        except Exception as e:
            st.session_state.recal_error = f"Fetch failed: {e}"
            st.rerun()
    with st.spinner("Running Claude calibration pass…"):
        try:
            raw_result = run_calibration_pass(registry)
            name_to_actor = {a["name"]: a for a in registry}
            valid, invalid_reasons = validate_adjustments(raw_result, name_to_actor, anchor_names)
            st.session_state.recal_valid = valid
            st.session_state.recal_invalid_reasons = invalid_reasons
            st.session_state.recal_distribution_notes = (raw_result.get("distribution_notes") or "").strip()
        except Exception as e:
            st.session_state.recal_error = str(e)
            st.rerun()
    st.rerun()

if st.session_state.recal_error:
    st.error(st.session_state.recal_error)
    st.session_state.recal_error = None

registry = st.session_state.recal_registry
valid_adjustments = st.session_state.recal_valid
invalid_reasons = st.session_state.recal_invalid_reasons
distribution_notes = st.session_state.recal_distribution_notes
approved_indices = st.session_state.recal_approved
written_result = st.session_state.recal_written

# ── Distribution panel (always show when we have registry) ────────────────────

if registry is not None:
    st.markdown("### Distribution")
    flagged_names = {a["actor_name"] for a in valid_adjustments}

    import pandas as pd
    rows = []
    for a in registry:
        rows.append({
            "Actor": a["name"],
            "Type": a.get("actor_type") or "",
            "Authority": a.get("authority") if a.get("authority") is not None else "—",
            "Reach": a.get("reach") if a.get("reach") is not None else "—",
            "PF Score": a.get("pf_score") if a.get("pf_score") is not None else "—",
            "Anchor": "Yes" if a["name"] in anchor_names else "",
            "Flagged": "Yes" if a["name"] in flagged_names else "",
        })
    df = pd.DataFrame(rows)

    def _row_highlight(row):
        if row["Anchor"] == "Yes":
            return ["background-color: #1e3a5f22;"] * len(row)
        if row["Flagged"] == "Yes":
            return ["background-color: #fef3c722;"] * len(row)
        return [""] * len(row)

    styled = df.style.apply(_row_highlight, axis=1)
    st.dataframe(styled, use_container_width=True, hide_index=True)
    st.caption("Anchor rows: blue tint. Flagged for adjustment: amber tint.")
    st.divider()

# ── Proposed adjustments ──────────────────────────────────────────────────────

if valid_adjustments:
    st.markdown("### Proposed adjustments")
    if distribution_notes:
        st.info(distribution_notes)
    if invalid_reasons:
        with st.expander("Validation messages (dropped items)", expanded=False):
            for r in invalid_reasons:
                st.text(r)

    high_conf = sum(1 for a in valid_adjustments if (a.get("confidence") or "").strip() == "High")
    med_conf = sum(1 for a in valid_adjustments if (a.get("confidence") or "").strip() == "Medium")
    low_conf = sum(1 for a in valid_adjustments if (a.get("confidence") or "").strip() == "Low")
    st.markdown(
        f"**{len(valid_adjustments)}** actors flagged — **{high_conf}** High, **{med_conf}** Medium, **{low_conf}** Low confidence"
    )

    for i, adj in enumerate(valid_adjustments):
        actor_name = adj.get("actor_name", "")
        actor_type = adj.get("actor_type", "")
        cur_a = adj.get("current_authority")
        cur_r = adj.get("current_reach")
        cur_pf = adj.get("current_pf_score")
        rec_a = adj.get("recommended_authority")
        rec_r = adj.get("recommended_reach")
        rec_pf = adj.get("recommended_pf_score")
        reason = (adj.get("adjustment_reason") or "").strip()
        rationale = (adj.get("calibration_rationale") or "").strip()
        confidence = (adj.get("confidence") or "").strip()

        delta_pf = (rec_pf - cur_pf) if cur_pf is not None else None
        abs_delta = abs(delta_pf) if delta_pf is not None else 0
        if abs_delta < 5:
            delta_color = "green"
        elif abs_delta <= 15:
            delta_color = "orange"
        else:
            delta_color = "red"

        with st.container():
            col_left, col_right = st.columns([3, 1])
            with col_left:
                st.markdown(f"**{actor_name}**")
                st.caption(f"Type: {actor_type}")
            with col_right:
                st.checkbox(
                    "Approve",
                    key=f"recal_approve_{i}",
                    value=(i in approved_indices),
                    label_visibility="collapsed",
                )

            cur_str = f"Authority {cur_a}, Reach {cur_r}, PF {cur_pf}" if cur_a is not None and cur_r is not None else "—"
            rec_str = f"Authority {rec_a}, Reach {rec_r}, PF {rec_pf}"
            delta_str = f"Δ PF {delta_pf:+.0f}" if delta_pf is not None else ""
            st.markdown(f"**Current:** {cur_str} → **Proposed:** {rec_str}")
            if delta_str:
                st.markdown(f":{delta_color}[**{delta_str}**]")
            st.markdown(f"**Reason:** {reason}  \n**Confidence:** {confidence}")
            st.markdown(f"*{rationale}*")
            st.divider()

    # Keep approved set in sync with checkboxes (Streamlit re-runs)
    new_approved = set()
    for i in range(len(valid_adjustments)):
        if st.session_state.get(f"recal_approve_{i}", False):
            new_approved.add(i)
    st.session_state.recal_approved = new_approved

    # ── Action bar ─────────────────────────────────────────────────────────────

    st.markdown("---")
    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("✅ Approve All High Confidence"):
            high_indices = {i for i, a in enumerate(valid_adjustments) if (a.get("confidence") or "").strip() == "High"}
            st.session_state.recal_approved = high_indices
            for i in high_indices:
                st.session_state[f"recal_approve_{i}"] = True
            st.rerun()
    with col2:
        approve_selected = st.button("✅ Approve Selected")
    with col3:
        discard = st.button("🗑 Discard All")
        if discard:
            with st.spinner("Logging run…"):
                try:
                    write_approved_changes([])  # Log "0 actors adjusted"
                except Exception:
                    pass
            _recal_reset_after_run()
            st.session_state.recal_valid = []
            st.rerun()

    if approve_selected:
        approved_list = [valid_adjustments[i] for i in st.session_state.recal_approved]
        with st.spinner("Writing to Notion…"):
            try:
                written_names, activity_id = write_approved_changes(approved_list)
                st.session_state.recal_written = (written_names, activity_id)
                st.session_state.recal_approved = set()
                if written_names:
                    st.success(f"Wrote {len(written_names)} adjustments to Actors Registry and Score Snapshots. Activity log updated.")
                else:
                    st.info("No adjustments selected. Activity log updated (0 actors adjusted).")
                st.rerun()
            except Exception as e:
                st.error(f"Write failed: {e}")

elif registry is not None and not run_clicked:
    st.info("Run a calibration pass to see proposed adjustments.")
elif registry is None:
    st.info("Click **Run calibration pass** to fetch the actor registry and run the calibration agent.")

# ── Show last write result ────────────────────────────────────────────────────

if written_result:
    names, _ = written_result
    st.success(f"Last run: **{len(names)}** actors updated: {', '.join(names[:10])}{'…' if len(names) > 10 else ''}")
