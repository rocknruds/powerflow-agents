"""PowerFlow PDF Screener — Streamlit application.

Drag-and-drop a PDF to screen it for geopolitical relevance before ingestion.
"""

from __future__ import annotations

import hashlib
import sys
import tempfile
from pathlib import Path

import streamlit as st

# Ensure the repo root is on sys.path so agents/config imports work
sys.path.insert(0, str(Path(__file__).parent.parent))

# ── Styles ────────────────────────────────────────────────────────────────────

st.markdown(
    """
    <style>
    /* Score circle */
    .score-circle {
        display: flex;
        align-items: center;
        justify-content: center;
        width: 120px;
        height: 120px;
        border-radius: 50%;
        font-size: 2.2rem;
        font-weight: 800;
        color: white;
        margin: 0 auto 1rem auto;
    }
    .score-green  { background: #16a34a; }
    .score-yellow { background: #ca8a04; }
    .score-red    { background: #dc2626; }

    /* Verdict banner */
    .verdict-banner {
        text-align: center;
        font-size: 1.4rem;
        font-weight: 700;
        letter-spacing: 0.05em;
        padding: 0.4rem 1rem;
        border-radius: 8px;
        margin-bottom: 1.2rem;
    }
    .verdict-strong   { background: #dcfce7; color: #14532d; }
    .verdict-moderate { background: #fef9c3; color: #713f12; }
    .verdict-weak     { background: #ffedd5; color: #7c2d12; }
    .verdict-none     { background: #fee2e2; color: #7f1d1d; }

    /* Database badges */
    .db-badge {
        display: inline-block;
        background: #1e3a5f;
        color: #93c5fd;
        border: 1px solid #3b82f6;
        border-radius: 20px;
        padding: 3px 12px;
        font-size: 0.78rem;
        font-weight: 600;
        margin: 3px 4px;
        letter-spacing: 0.03em;
    }

    /* Section headers */
    .section-label {
        font-size: 0.7rem;
        font-weight: 700;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: #6b7280;
        margin-bottom: 0.4rem;
    }

    /* Signal bullets */
    .signal-item {
        padding: 6px 0;
        border-bottom: 1px solid #1f2937;
        font-size: 0.9rem;
    }
    .signal-item:last-child { border-bottom: none; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ── Region inference helper ───────────────────────────────────────────────────

_REGION_KEYWORDS: dict[str, list[str]] = {
    "Middle East": ["iran", "israel", "iraq", "syria", "lebanon", "gulf",
                    "saudi", "yemen", "houthi", "irgc", "hezbollah", "qatar",
                    "uae", "bahrain", "jordan"],
    "Russia-FSU": ["russia", "ukraine", "putin", "kremlin", "nato", "belarus",
                   "moldova", "caucasus", "central asia"],
    "Europe": ["europe", "eu", "france", "germany", "uk", "britain", "nato",
               "brussels", "poland"],
    "South Asia": ["pakistan", "india", "afghanistan", "taliban", "ttp",
                   "kashmir", "bangladesh"],
    "East Asia": ["china", "ccp", "taiwan", "north korea", "dprk", "xi",
                  "south china sea", "japan", "korea"],
    "Sub-Saharan Africa": ["sahel", "mali", "niger", "sudan", "rsf", "somalia",
                           "ethiopia", "wagner", "africa corps"],
    "North Africa": ["egypt", "libya", "algeria", "morocco", "tunisia"],
    "Latin America": ["venezuela", "mexico", "colombia", "cartel", "maduro",
                      "cuba", "nicaragua"],
}


def _infer_region_tags(signals: list[str]) -> list[str]:
    """Infer region tags from screener key_signals text."""
    combined = " ".join(signals).lower()
    return [
        region for region, keywords in _REGION_KEYWORDS.items()
        if any(kw in combined for kw in keywords)
    ] or ["Global"]


# ── Session state keys ────────────────────────────────────────────────────────

def _reset_state() -> None:
    for key in (
        "screen_result",
        "pdf_bytes",
        "pdf_name",
        "pdf_hash",
        "ingestion_status",
        "pdf_novelty_result",
        "pdf_extraction",
    ):
        st.session_state.pop(key, None)


def _reset_uploader() -> None:
    st.session_state["uploader_key"] += 1


if "uploader_key" not in st.session_state:
    st.session_state["uploader_key"] = 0

# ── Header ────────────────────────────────────────────────────────────────────

st.markdown("## 📄 PowerFlow PDF Screener")
st.markdown(
    "Upload a PDF to evaluate its relevance to the PowerFlow geopolitical intelligence mission "
    "before committing it to Notion."
)
st.divider()

# ── Upload ────────────────────────────────────────────────────────────────────

uploaded_file = st.file_uploader(
    "Drop a PDF here or click to browse",
    type=["pdf"],
    help="PDF will be screened locally — nothing is written to Notion until you confirm.",
    key=f"pdf_uploader_{st.session_state['uploader_key']}",
)

if uploaded_file is None:
    _reset_state()
    st.stop()

# Detect a new upload by content hash so re-uploading the same filename
# with different content (or after a prompt update) always triggers a fresh screen.
pdf_bytes: bytes = uploaded_file.read()
file_hash = hashlib.md5(pdf_bytes).hexdigest()

if st.session_state.get("pdf_hash") != file_hash:
    _reset_state()
    st.session_state["pdf_hash"] = file_hash
    st.session_state["pdf_name"] = uploaded_file.name
    st.session_state["pdf_bytes"] = pdf_bytes

pdf_bytes = st.session_state["pdf_bytes"]

# ── Screen the PDF ────────────────────────────────────────────────────────────

if "screen_result" not in st.session_state:
    with st.spinner("Screening document for geopolitical relevance…"):
        from agents.ingest.screener import screen

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(pdf_bytes)
            tmp_path = tmp.name

        try:
            result = screen(tmp_path)
            st.session_state["screen_result"] = result
        except Exception as exc:
            st.error(f"Screening failed: {exc}")
            st.stop()

result: dict = st.session_state["screen_result"]

# ── Start Over button ─────────────────────────────────────────────────────────

_spacer, _btn_col = st.columns([7, 2])
with _btn_col:
    if st.button("↩ Start Over", help="Reset and upload a new document"):
        _reset_state()
        _reset_uploader()
        st.rerun()

# ── Render results ────────────────────────────────────────────────────────────

score: int = result["score"]
verdict: str = result["verdict"]
reasoning: str = result["reasoning"]
affected_dbs: list[str] = result["affected_databases"]
key_signals: list[str] = result["key_signals"]

# Score colour
if score >= 70:
    score_cls = "score-green"
    verdict_cls = "verdict-strong"
elif score >= 40:
    score_cls = "score-yellow"
    verdict_cls = "verdict-moderate"
elif score >= 10:
    score_cls = "score-yellow"
    verdict_cls = "verdict-weak"
else:
    score_cls = "score-red"
    verdict_cls = "verdict-none"

# Score circle
st.markdown(
    f'<div class="score-circle {score_cls}">{score}%</div>',
    unsafe_allow_html=True,
)

# Verdict banner
st.markdown(
    f'<div class="verdict-banner {verdict_cls}">{verdict}</div>',
    unsafe_allow_html=True,
)

# Reasoning
st.markdown('<p class="section-label">Reasoning</p>', unsafe_allow_html=True)
st.markdown(reasoning)

st.write("")

# Affected databases
if affected_dbs:
    st.markdown('<p class="section-label">Affected Databases</p>', unsafe_allow_html=True)
    badges_html = "".join(f'<span class="db-badge">{db}</span>' for db in affected_dbs)
    st.markdown(f'<div>{badges_html}</div>', unsafe_allow_html=True)
    st.write("")

# Key signals
if key_signals:
    st.markdown('<p class="section-label">Key Signals</p>', unsafe_allow_html=True)
    signals_html = "".join(
        f'<div class="signal-item">▸ &nbsp;{sig}</div>' for sig in key_signals
    )
    st.markdown(f'<div>{signals_html}</div>', unsafe_allow_html=True)

st.divider()

# ── Auto-Extraction (runs after screening passes, before novelty check) ───────

if score >= 40:
    if "pdf_extraction" not in st.session_state:
        with st.spinner("Extracting intelligence…"):
            try:
                from agents.ingest import extractor
                from agents.ingest.screener import extract_text_from_pdf

                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                    tmp.write(pdf_bytes)
                    tmp_path = tmp.name

                text = extract_text_from_pdf(tmp_path)
                if not text.strip():
                    raise ValueError("Could not extract text from the PDF.")

                data = extractor.extract(text)
                st.session_state["pdf_extraction"] = data
            except Exception as exc:
                st.error(f"Extraction failed: {exc}")
                # Do not block — user can still discard

# ── Novelty Check ─────────────────────────────────────────────────────────────

if score >= 40:
    if "pdf_novelty_result" not in st.session_state:
        with st.spinner("Checking novelty against existing Intel Feeds…"):
            from agents.ingest.novelty_checker import check_novelty

            extracted = st.session_state.get("pdf_extraction", {})
            actor_names = [a["name"] for a in extracted.get("actors", [])]

            screen_result = st.session_state["screen_result"]
            region_tags = _infer_region_tags(screen_result.get("key_signals", []))

            novelty = check_novelty(
                article_title=screen_result.get("title", st.session_state.get("pdf_name", "Unknown")),
                article_summary=screen_result.get("reasoning", ""),
                article_argument="; ".join(screen_result.get("key_signals", [])),
                actors=actor_names,
                region_tags=region_tags,
            )
            st.session_state["pdf_novelty_result"] = novelty

    novelty = st.session_state["pdf_novelty_result"]
    novelty_verdict = novelty.get("verdict", "New Signal")
    novelty_score = novelty.get("novelty_score", 100)
    novelty_reasoning = novelty.get("reasoning", "")
    new_elements = novelty.get("new_elements")

    verdict_icons = {
        "New Signal": "🟢",
        "Confirming": "🟡",
        "Redundant": "🔴",
    }
    icon = verdict_icons.get(novelty_verdict, "⚪")

    st.markdown(f"**Novelty:** {icon} `{novelty_verdict}` — Score: {novelty_score}/100")
    st.caption(novelty_reasoning)
    if new_elements:
        st.caption(f"New elements: {new_elements}")

    if novelty_verdict == "Redundant":
        st.warning(
            "This article appears redundant with existing Intel Feeds. "
            "Consider discarding or logging source only."
        )
    elif novelty_verdict == "Confirming":
        st.info(
            "This article confirms existing assessments. "
            "You can log the source without writing a full Intel Feed entry."
        )

    st.divider()
else:
    novelty_verdict = "New Signal"

# ── Action buttons ────────────────────────────────────────────────────────────

log_source_clicked = False
run_clicked = False

if novelty_verdict == "Redundant":
    col_discard, col_run = st.columns([1, 1], gap="medium")

    with col_discard:
        if st.button("🗑 Discard", use_container_width=True, type="primary"):
            _reset_state()
            _reset_uploader()
            st.rerun()

    with col_run:
        run_clicked = st.button(
            "🚀 Ingest Anyway",
            use_container_width=True,
        )

elif novelty_verdict == "Confirming":
    col_run, col_log, col_discard = st.columns([1, 1, 1], gap="medium")

    with col_discard:
        if st.button("🗑 Discard", use_container_width=True):
            _reset_state()
            _reset_uploader()
            st.rerun()

    with col_log:
        log_source_clicked = st.button(
            "📌 Log Source Only",
            use_container_width=True,
        )

    with col_run:
        run_clicked = st.button(
            "🚀 Ingest Full",
            use_container_width=True,
            type="primary",
        )

else:
    col_run, col_discard = st.columns([1, 1], gap="medium")

    with col_discard:
        if st.button("🗑 Discard", use_container_width=True):
            _reset_state()
            _reset_uploader()
            st.rerun()

    with col_run:
        run_clicked = st.button(
            "🚀 Run Ingestion",
            use_container_width=True,
            type="primary",
        )

# ── Log Source Only (Confirming path) ────────────────────────────────────────

if log_source_clicked:
    if "ingestion_status" not in st.session_state:
        with st.spinner("Logging source to Notion…"):
            try:
                from agents.ingest import notion_writer

                data = st.session_state.get("pdf_extraction")
                if data is None:
                    from agents.ingest import extractor
                    from agents.ingest.screener import extract_text_from_pdf

                    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                        tmp.write(pdf_bytes)
                        tmp_path = tmp.name

                    text = extract_text_from_pdf(tmp_path)
                    if not text.strip():
                        raise ValueError("Could not extract text from the PDF.")
                    data = extractor.extract(text)

                source_data = data["source"]

                source_page_id, source_page_url = notion_writer.write_source(source_data)

                notion_writer.write_activity_log(
                    article_title=source_data.get("title", "Untitled"),
                    screening_score=st.session_state["screen_result"].get("score"),
                    screening_verdict=st.session_state["screen_result"].get("verdict"),
                    databases_written=["Sources"],
                    actor_count=0,
                    status="Completed",
                    notes="Novelty: Confirming — source logged only, Intel Feed skipped.",
                )

                st.session_state["ingestion_status"] = {
                    "success": True,
                    "log_only": True,
                    "source_url": source_page_url,
                }
            except Exception as exc:
                st.session_state["ingestion_status"] = {
                    "success": False,
                    "error": str(exc),
                }

# ── Full Ingestion ────────────────────────────────────────────────────────────

if run_clicked:
    if "ingestion_status" not in st.session_state:
        with st.spinner("Writing to Notion…"):
            try:
                from agents.ingest import notion_writer

                data = st.session_state.get("pdf_extraction")
                if data is None:
                    from agents.ingest import extractor
                    from agents.ingest.screener import extract_text_from_pdf

                    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                        tmp.write(pdf_bytes)
                        tmp_path = tmp.name

                    text = extract_text_from_pdf(tmp_path)
                    if not text.strip():
                        raise ValueError("Could not extract text from the PDF.")
                    data = extractor.extract(text)

                source_data = data["source"]
                event_data = data["event"]
                intel_feed_data = data.get("intel_feed", {})

                source_page_id, source_page_url = notion_writer.write_source(source_data)
                event_page_id, event_page_url = notion_writer.write_event(
                    event_data, source_page_id
                )
                intel_page_id, intel_page_url = notion_writer.write_intel_feed(
                    source_data, event_data, st.session_state["screen_result"], intel_feed_data
                )
                actor_results = notion_writer.write_actors(
                    data.get("actors", []), event_page_id
                )
                registry_results = [r for r in actor_results if r[4]]

                from agents.ingest.conflict_matcher import run_conflict_matching
                run_conflict_matching(event_page_id, event_data, data.get("actors", []))

                notion_writer.patch_intel_feed(
                    intel_page_id=intel_page_id,
                    actor_page_ids=[r[0] for r in actor_results],
                    source_page_id=source_page_id,
                    event_page_id=event_page_id,
                )

                # Score actors after ingestion
                from agents.score.score_agent import score_actors
                actor_ids = [r[0] for r in registry_results]
                score_results = score_actors(actor_ids) if actor_ids else []

                actor_names_str = ", ".join(r[2] for r in actor_results)
                scored_count = sum(1 for r in score_results if r.get("success"))
                novelty_note = (
                    f"Novelty: {novelty_verdict} | " if novelty_verdict != "New Signal" else ""
                )
                notion_writer.write_activity_log(
                    article_title=source_data.get("title", "Untitled"),
                    screening_score=st.session_state["screen_result"].get("score"),
                    screening_verdict=st.session_state["screen_result"].get("verdict"),
                    databases_written=["Sources", "Events Timeline", "Intelligence Feeds", "Actors Registry"],
                    actor_count=len(actor_results),
                    status="Completed",
                    notes=f"{novelty_note}Actors: {actor_names_str} | Scored: {scored_count}/{len(registry_results)}",
                )

                st.session_state["ingestion_status"] = {
                    "success": True,
                    "log_only": False,
                    "source_url": source_page_url,
                    "event_url": event_page_url,
                    "intel_url": intel_page_url,
                    "actors": actor_results,
                    "score_results": score_results,
                }
            except Exception as exc:
                st.session_state["ingestion_status"] = {
                    "success": False,
                    "error": str(exc),
                }

# ── Show ingestion outcome ────────────────────────────────────────────────────

if status := st.session_state.get("ingestion_status"):
    if status["success"]:
        if status.get("log_only"):
            st.success("Source logged to Notion — Intel Feed write skipped (Confirming).")
            st.markdown(f"**Source:** [{status['source_url']}]({status['source_url']})")
        else:
            st.success("Ingestion complete — records written to Notion.")
            st.markdown(f"**Source:** [{status['source_url']}]({status['source_url']})")
            st.markdown(f"**Event:** [{status['event_url']}]({status['event_url']})")
            st.markdown(f"**Intel Feed:** [{status['intel_url']}]({status['intel_url']})")

            actor_results: list[tuple[str, str, str, bool, bool]] = status.get("actors", [])
            if actor_results:
                st.markdown("**Actors:**")
                for _page_id, page_url, actor_name, is_new, _ in actor_results:
                    label = "new" if is_new else "existing"
                    st.markdown(f"- [{actor_name}]({page_url}) `({label})`")
            else:
                st.markdown("**Actors:** none extracted")

            score_results: list[dict] = status.get("score_results", [])
            if score_results:
                st.markdown("**PF Scores:**")
                for r in score_results:
                    if r["success"]:
                        pf = r["pf_score"]
                        st.markdown(
                            f"- **{r['actor_name']}** — "
                            f"Authority: `{r['authority_score']}` | "
                            f"Reach: `{r['reach_score']}` | "
                            f"**PF Score: `{pf:.0f}`**"
                        )
    else:
        st.error(f"Ingestion failed: {status['error']}")
