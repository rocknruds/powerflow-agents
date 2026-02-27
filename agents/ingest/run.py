"""CLI entrypoint for the PowerFlow ingestion agent."""

import argparse
import sys

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from agents.ingest import extractor, notion_writer, scraper

console = Console()


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m agents.ingest.run",
        description="PowerFlow Ingestion Agent — extract geopolitical events from articles.",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--url", metavar="URL", help="URL of the article to ingest")
    group.add_argument("--text", metavar="TEXT", help="Raw article text to ingest")
    args = parser.parse_args()

    # ── 1. Acquire text ───────────────────────────────────────────────────────
    url: str | None = None

    if args.url:
        url = args.url
        console.print(f"\n[bold cyan]Fetching:[/bold cyan] {url}")
        try:
            text = scraper.fetch_url(url)
        except RuntimeError as exc:
            console.print(f"\n[bold red]Scraping failed:[/bold red] {exc}")
            console.print(
                "[dim]Tip: paywalled or JS-rendered pages cannot be scraped. "
                "Use [bold]--text[/bold] to paste the article content instead.[/dim]"
            )
            sys.exit(1)
        console.print(
            f"[green]✓[/green] Fetched {len(text):,} chars of article text."
        )

    elif args.text:
        text = args.text

    else:
        console.print("\n[bold]PowerFlow Ingestion Agent[/bold]")
        console.print("No input provided. Enter article URL or paste text below.\n")
        console.print(
            "[dim]Options:\n"
            "  (u) Enter a URL\n"
            "  (t) Paste article text\n[/dim]"
        )
        choice = console.input("[bold]Choice [u/t]:[/bold] ").strip().lower()

        if choice == "u":
            url = console.input("[bold]URL:[/bold] ").strip()
            console.print(f"\n[bold cyan]Fetching:[/bold cyan] {url}")
            try:
                text = scraper.fetch_url(url)
            except RuntimeError as exc:
                console.print(f"\n[bold red]Scraping failed:[/bold red] {exc}")
                sys.exit(1)
            console.print(
                f"[green]✓[/green] Fetched {len(text):,} chars of article text."
            )
        elif choice == "t":
            console.print(
                "[dim]Paste your article text below. Press Enter twice when done.[/dim]\n"
            )
            lines = []
            while True:
                line = input()
                if line == "" and lines and lines[-1] == "":
                    break
                lines.append(line)
            text = "\n".join(lines).strip()
        else:
            console.print("[red]Invalid choice. Exiting.[/red]")
            sys.exit(1)

    if not text.strip():
        console.print("[bold red]Error:[/bold red] No text to process.")
        sys.exit(1)

    # ── 2. Extract with Claude ────────────────────────────────────────────────
    console.print("\n[bold cyan]Extracting...[/bold cyan] Sending text to Claude.")
    try:
        data = extractor.extract(text)
    except RuntimeError as exc:
        console.print(f"\n[bold red]Extraction failed:[/bold red] {exc}")
        sys.exit(1)

    source_data = data["source"]
    event_data = data["event"]

    # Attach the URL to source data if we scraped it
    if url:
        source_data["url"] = url

    # ── 3. Display extraction results ─────────────────────────────────────────
    _print_extraction(source_data, event_data)

    # ── 4. Confirm before writing ─────────────────────────────────────────────
    confirm = console.input(
        "\n[bold]Write these records to Notion? [y/N]:[/bold] "
    ).strip().lower()
    if confirm != "y":
        console.print("[dim]Aborted. Nothing was written to Notion.[/dim]")
        sys.exit(0)

    # ── 5. Write Source to Notion ─────────────────────────────────────────────
    console.print("\n[bold cyan]Writing Source record...[/bold cyan]")
    try:
        source_page_id, source_page_url = notion_writer.write_source(source_data)
    except RuntimeError as exc:
        console.print(f"\n[bold red]Notion write failed (Source):[/bold red] {exc}")
        sys.exit(1)
    console.print(f"[green]✓[/green] Source created: {source_page_url}")

    # ── 6. Write Event to Notion ──────────────────────────────────────────────
    console.print("\n[bold cyan]Writing Event record...[/bold cyan]")
    try:
        event_page_id, event_page_url = notion_writer.write_event(
            event_data, source_page_id
        )
    except RuntimeError as exc:
        console.print(f"\n[bold red]Notion write failed (Event):[/bold red] {exc}")
        sys.exit(1)
    console.print(f"[green]✓[/green] Event created: {event_page_url}")

    # ── 7. Write Intel Feed to Notion ─────────────────────────────────────────
    console.print("\n[bold cyan]Writing Intel Feed record...[/bold cyan]")
    screen_result_stub = {"score": 50, "reasoning": "Manually ingested via CLI."}
    try:
        intel_page_id, intel_page_url = notion_writer.write_intel_feed(
            source_data, event_data, screen_result_stub
        )
    except RuntimeError as exc:
        console.print(f"\n[bold red]Notion write failed (Intel Feed):[/bold red] {exc}")
        sys.exit(1)
    console.print(f"[green]✓[/green] Intel Feed created: {intel_page_url}")

    # ── 8. Write Actors to Notion ─────────────────────────────────────────────
    console.print("\n[bold cyan]Writing Actor records...[/bold cyan]")
    try:
        actor_results = notion_writer.write_actors(data.get("actors", []), event_page_id)
    except RuntimeError as exc:
        console.print(f"\n[bold red]Notion write failed (Actors):[/bold red] {exc}")
        sys.exit(1)
    for _pid, actor_url, actor_name, is_new in actor_results:
        label = "new" if is_new else "existing"
        console.print(f"[green]✓[/green] {actor_name} ({label}): {actor_url}")

    # ── 9. Write Activity Log ─────────────────────────────────────────────────
    console.print("\n[bold cyan]Writing Activity Log entry...[/bold cyan]")
    source_title = source_data.get("title", "Untitled")
    actor_names = ", ".join(name for _, _, name, _ in actor_results)
    log_summary = (
        f"Ingested source, event, intel feed, and {len(actor_results)} actor(s) "
        f"from {source_title}"
    )
    raw_reliability = source_data.get("reliability", "")
    log_confidence = "High" if raw_reliability == "High" else "Medium"
    try:
        notion_writer.write_activity_log(
            log_title=source_title,
            summary=log_summary,
            action_type="Create",
            target_database="Events Timeline",
            target_record=event_data.get("event_name", ""),
            source_material=url or "",
            confidence=log_confidence,
            notes=actor_names,
        )
    except RuntimeError as exc:
        console.print(f"\n[bold red]Notion write failed (Activity Log):[/bold red] {exc}")
        sys.exit(1)
    console.print("[green]✓[/green] Activity log entry created.")

    # ── 10. Final summary ─────────────────────────────────────────────────────
    console.print(
        Panel(
            f"[bold green]✓ Ingestion complete[/bold green]\n\n"
            f"[bold]Source:[/bold]     {source_page_url}\n"
            f"[bold]Event:[/bold]      {event_page_url}\n"
            f"[bold]Intel Feed:[/bold] {intel_page_url}\n"
            f"[bold]Actors:[/bold]     {len(actor_results)} written",
            title="PowerFlow",
            border_style="green",
        )
    )


def _print_extraction(source: dict, event: dict) -> None:
    """Render a rich panel summarising the extracted data."""
    source_table = Table(show_header=False, box=None, padding=(0, 1))
    source_table.add_column("Field", style="bold dim", min_width=24)
    source_table.add_column("Value")

    source_table.add_row("Title", source.get("title", ""))
    source_table.add_row("Author / Organization", source.get("author_organization", ""))
    source_table.add_row("Publication Date", source.get("publication_date", ""))
    source_table.add_row("Source Type", source.get("source_type", ""))
    source_table.add_row("Reliability", source.get("reliability", ""))
    source_table.add_row("Summary", source.get("summary", ""))

    event_table = Table(show_header=False, box=None, padding=(0, 1))
    event_table.add_column("Field", style="bold dim", min_width=24)
    event_table.add_column("Value")

    event_table.add_row("Event Name", event.get("event_name", ""))
    event_table.add_row("Date", event.get("date", ""))
    event_table.add_row("Event Type", event.get("event_type", ""))
    event_table.add_row("Description", event.get("description", ""))
    event_table.add_row("Impact on Sovereignty Gap", event.get("impact_on_sovereignty_gap", ""))

    console.print(
        Panel(source_table, title="[bold]Source[/bold]", border_style="blue")
    )
    console.print(
        Panel(event_table, title="[bold]Event[/bold]", border_style="magenta")
    )


if __name__ == "__main__":
    main()
