import requests
from config.settings import NOTION_API_KEY
from agents.score.score_agent import score_actors

ACTORS_DB_ID = "7aa6bbc818ad4a35a4059fbe2537d115"


def fetch_all_actor_ids():
    url = f"https://api.notion.com/v1/databases/{ACTORS_DB_ID}/query"
    headers = {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28",
    }
    ids = []
    start_cursor = None

    while True:
        payload = {}
        if start_cursor:
            payload["start_cursor"] = start_cursor
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        for page in data.get("results", []):
            ids.append(page["id"])
        if data.get("has_more") and data.get("next_cursor"):
            start_cursor = data["next_cursor"]
        else:
            break

    return ids


actor_ids = fetch_all_actor_ids()
print(f"Found {len(actor_ids)} actors. Rescoring...\n")

results = score_actors(actor_ids)

succeeded = [r for r in results if r["success"]]
failed = [r for r in results if not r["success"]]
ceilings = [r for r in results if r.get("ceiling_applied")]

print(f"\n--- Rescore Complete ---")
print(f"Scored:          {len(succeeded)}/{len(results)}")
print(f"Ceiling applied: {len(ceilings)}")
print(f"Failed:          {len(failed)}")
print()

for r in succeeded:
    ceiling_flag = " [ceiling]" if r.get("ceiling_applied") else ""
    print(
        f"  {r['actor_name']:<35} "
        f"Auth: {r['authority_score']:>3} | "
        f"Reach: {r['reach_score']:>3} | "
        f"PF: {r['pf_score']:>5.1f}"
        f"{ceiling_flag}"
    )

if failed:
    print("\nFailed actors:")
    for r in failed:
        print(f"  {r['actor_name']} — {r['error']}")