# test_score.py (create this at repo root)
from agents.score.score_agent import score_actors

# Pakistan and Taliban page IDs from our earlier ingestion
# Pull these from your Actors Registry in Notion — just grab the page IDs from the URLs
actor_ids = [
    "314f8ae9-4162-811f-b20f-eb10c0e9ac46",  # Pakistan
    "314f8ae9-4162-8166-85ef-d627aa0e6bc0",  # Islamic Emirate of Afghanistan (Taliban)
    "314f8ae9-4162-8198-b844-d843e710d5c3",  # Tehreek-e-Taliban Pakistan (TTP)
    "312f8ae9-4162-8135-ac0c-d2cc89635291",  # Pakistan — ISI
]
results = score_actors(actor_ids)
for r in results:
    print(f"\n{r['actor_name']}")
    print(f"  Authority: {r['authority_score']}")
    print(f"  Reach:     {r['reach_score']}")
    pf = r['pf_score']
    print(f"  PF Score:  {pf:.0f}" if pf is not None else "  PF Score:  None")
    print(f"  Reasoning: {r['reasoning']}")
    if not r['success']:
        print(f"  ERROR: {r['error']}")
