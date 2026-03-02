# test_score.py (create this at repo root)
from agents.score.score_agent import score_actors

# Pakistan and Taliban page IDs from our earlier ingestion
# Pull these from your Actors Registry in Notion — just grab the page IDs from the URLs
actor_ids = [
    "312f8ae9-4162-8114-9ecb-f5ac14c983dc"
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
