# paste into score.py or run interactively
from agents.score.score_agent import score_actors

# Houthis page ID from your Actors Registry
results = score_actors(["315f8ae941628145a0eaff2ce22ef04c"])
for r in results:
    print(f"Authority: {r['authority_score']}")
    print(f"Reach: {r['reach_score']}")
    print(f"PF: {r['pf_score']:.0f}")
    print(f"Ceiling applied: {r['ceiling_applied']}")
    print(f"Reasoning: {r['reasoning']}")
