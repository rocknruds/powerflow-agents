"""PowerFlow URL Ingestion — Streamlit page.

Fetch an article by URL, extract geopolitical intelligence, and write to Notion.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

# Ensure the repo root is on sys.path so agents/config imports work
sys.path.insert(0, str(Path(__file__).parent.parent))

# ── Header ────────────────────────────────────────────────────────────────────

st.markdown("## 🌐 PowerFlow URL Ingestion")
st.markdown(
    "Enter a URL to fetch the article, extract geopolitical intelligence, "
    "and write records to Notion."
)
st.divider()

# ── Session state init ────────────────────────────────────────────────────────

if "url_extraction" not in st.session_state:
    st.session_state.url_extraction = None  # dict with source/event/actors/url
if "url_ingestion_status" not in st.session_state:
    st.session_state.url_ingestion_status = None  # dict with Notion write results

# ── URL input ─────────────────────────────────────────────────────────────────

url_input = st.text_input(
    "Article URL",
    placeholder="https://example.com/article",
    help="The page must be publicly accessible HTML. Paywalled or JS-rendered pages may fail.",
)

fetch_clicked = st.button(
    "🔍 Fetch & Extract",
    type="primary",
    disabled=not url_input.strip(),
)

# Reset downstream state when the URL changes
if url_input.strip() and (
    st.session_state.url_extraction is None
    or st.session_state.url_extraction.get("url") != url_input.strip()
):
    st.session_state.url_extraction = None
    st.session_state.url_ingestion_status = None

# ── Fetch & Extract ───────────────────────────────────────────────────────────

if fetch_clicked and url_input.strip():
    st.session_state.url_extraction = None
    st.session_state.url_ingestion_status = None

    with st.spinner("Fetching article and extracting intelligence…"):
        try:
            from agents.ingest import extractor, scraper

            text = scraper.fetch_url(url_input.strip())
            data = extractor.extract(text)

            source_data = data["source"]
            source_data["url"] = url_input.strip()

            st.session_state.url_extraction = {
                "url": url_input.strip(),
                "source": source_data,
                "event": data["event"],
                "actors": data.get("actors", []),
            }
        except RuntimeError as exc:
            st.error(
                f"**Scraping failed:** {exc}\n\n"
                "If the page is paywalled or JavaScript-rendered, try copying the "
                "article text and using the PDF ingestion page instead."
            )
        except Exception as exc:
            st.error(f"**Extraction failed:** {exc}")

# ── Display extraction results ────────────────────────────────────────────────

extraction = st.session_state.url_extraction

if extraction:
    source = extraction["source"]
    event = extraction["event"]
    actors = extraction["actors"]

    with st.expander("📰 Source", expanded=True):
        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown(f"**Title:** {source.get('title', '—')}")
            st.markdown(f"**Author / Org:** {source.get('author_organization', '—')}")
            st.markdown(f"**Publication Date:** {source.get('publication_date', '—')}")
        with col_b:
            st.markdown(f"**Source Type:** {source.get('source_type', '—')}")
            st.markdown(f"**Reliability:** {source.get('reliability', '—')}")
        st.markdown(f"**Summary:** {source.get('summary', '—')}")

    with st.expander("📌 Event", expanded=True):
        col_c, col_d = st.columns(2)
        with col_c:
            st.markdown(f"**Event Name:** {event.get('event_name', '—')}")
            st.markdown(f"**Date:** {event.get('date', '—')}")
            st.markdown(f"**Event Type:** {event.get('event_type', '—')}")
        with col_d:
            st.markdown(f"**PF Signal:** {event.get('pf_signal', '—')}")
        st.markdown(f"**Description:** {event.get('description', '—')}")

    if actors:
        with st.expander(f"🎭 Actors ({len(actors)})", expanded=False):
            for actor in actors:
                name = actor.get("name") or actor if isinstance(actor, str) else str(actor)
                st.markdown(f"- {name}")

    st.divider()

    # ── Write to Notion ───────────────────────────────────────────────────────

    write_clicked = st.button(
        "✅ Write to Notion",
        type="primary",
        use_container_width=True,
        disabled=bool(st.session_state.url_ingestion_status),
    )

    if write_clicked:
        with st.spinner("Writing records to Notion…"):
            try:
                from agents.ingest import notion_writer
                from agents.score.score_agent import score_actors

                screen_result_stub = {
                    "score": 50,
                    "reasoning": "Manually ingested via URL.",
                }

                source_page_id, source_page_url = notion_writer.write_source(source)
                event_page_id, event_page_url = notion_writer.write_event(
                    event, source_page_id
                )
                intel_page_id, intel_page_url = notion_writer.write_intel_feed(
                    source, event, screen_result_stub
                )
                actor_results = notion_writer.write_actors(actors, event_page_id)
                registry_results = [r for r in actor_results if r[4]]

                from agents.ingest.conflict_matcher import run_conflict_matching
                run_conflict_matching(event_page_id, event, actors)

                actor_ids = [r[0] for r in registry_results]
                score_results = score_actors(actor_ids) if actor_ids else []

                actor_names = ", ".join(r[2] for r in actor_results)
                scored_count = sum(1 for r in score_results if r.get("success"))
                notion_writer.write_activity_log(
                    article_title=source.get("title", "Untitled"),
                    screening_score=None,
                    screening_verdict=None,
                    databases_written=["Sources", "Events Timeline", "Intelligence Feeds", "Actors Registry"],
                    actor_count=len(actor_results),
                    status="Completed",
                    notes=f"Actors: {actor_names} | Scored: {scored_count}/{len(registry_results)}",
                )

                st.session_state.url_ingestion_status = {
                    "success": True,
                    "source_url": source_page_url,
                    "event_url": event_page_url,
                    "intel_url": intel_page_url,
                    "actors": actor_results,
                    "score_results": score_results,
                }
            except Exception as exc:
                st.session_state.url_ingestion_status = {
                    "success": False,
                    "error": str(exc),
                }

# ── Show Notion write outcome ─────────────────────────────────────────────────

if status := st.session_state.url_ingestion_status:
    if status["success"]:
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
                    st.markdown(f"- **{r['actor_name']}** — scoring failed: {r['error']}")
    else:
        st.error(f"Ingestion failed: {status['error']}")
