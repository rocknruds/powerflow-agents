"""One-time migration script to update the Actors Registry schema for the Score Agent.

Adds Authority Score, Reach Score, Score Reasoning, and Last Scored properties.
Removes the legacy Influence Score property if present.

Usage:
    python -m agents.score.migrate_schema
"""

from notion_client import Client
from notion_client.errors import APIResponseError

from config.settings import NOTION_ACTORS_DB_ID, NOTION_API_KEY


def main() -> None:
    client = Client(auth=NOTION_API_KEY)

    print("Fetching Actors Registry schema...")
    try:
        db = client.databases.retrieve(database_id=NOTION_ACTORS_DB_ID)
    except APIResponseError as exc:
        print(f"ERROR: Could not fetch database: {exc.status} — {exc.body}")
        return

    existing_props: dict = db.get("properties", {})
    print(f"\nCurrent properties ({len(existing_props)}):")
    for prop_name, prop_data in existing_props.items():
        print(f"  - {prop_name} ({prop_data.get('type', 'unknown')})")
    print()

    # ── Remove Influence Score ────────────────────────────────────────────────

    if "Influence Score" in existing_props:
        print("Removing 'Influence Score'...")
        try:
            client.databases.update(
                database_id=NOTION_ACTORS_DB_ID,
                properties={"Influence Score": None},
            )
            print("  ✓ Removed 'Influence Score'")
        except APIResponseError as exc:
            print(f"  ✗ Could not remove 'Influence Score': {exc.body}")
    else:
        print("'Influence Score' not found — skipping removal.")

    print()

    # ── Add new properties ────────────────────────────────────────────────────

    to_add: dict[str, dict] = {
        "Authority Score": {"number": {"format": "number"}},
        "Reach Score": {"number": {"format": "number"}},
        "Score Reasoning": {"rich_text": {}},
        "Last Scored": {"date": {}},
    }

    for prop_name, prop_schema in to_add.items():
        if prop_name in existing_props:
            print(f"'{prop_name}' already exists — skipping.")
            continue
        print(f"Adding '{prop_name}'...")
        try:
            client.databases.update(
                database_id=NOTION_ACTORS_DB_ID,
                properties={prop_name: prop_schema},
            )
            print(f"  ✓ Added '{prop_name}'")
        except APIResponseError as exc:
            print(f"  ✗ Could not add '{prop_name}': {exc.body}")

    print()
    print("=" * 60)
    print("NOTE: PF Score formula must be added manually in Notion.")
    print("Notion's API does not support creating formula properties.")
    print()
    print("  1. Open the Actors Registry database in Notion")
    print("  2. Click '+' to add a new property → select 'Formula'")
    print('  3. Name it "PF Score"')
    print('  4. Enter formula: prop("Authority Score") * 0.6 + prop("Reach Score") * 0.4')
    print("=" * 60)
    print()
    print("Migration complete.")


if __name__ == "__main__":
    main()
