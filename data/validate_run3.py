"""Validation round-robin for run 3 (added after it was trained)."""
from soccersim.selfplay.league import League

lg = League("data/models", "data/selfplay_pool_v2", run_dir="data/models/runs/run_3")
v = lg.validate(workers=4)
print("validated", len(v["teams"]), "teams,", v["games_per_pair"], "games per pair")
