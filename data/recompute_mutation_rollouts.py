"""Recompute run 3's mutation-filter rollouts (same seed, so the same mutants) and store every
reward in data/models/generator_metrics.json, which only kept means when run 3 was trained."""
import json
from pathlib import Path

from soccersim.config import load_config
from soccersim.generator.train import mutation_filter
from soccersim.schema import load_library
from soccersim.selfplay.runs import prior_promoted

cfg = load_config("training")
mf = mutation_filter(load_library(), cfg["mutation"][cfg["profile"]], 0, 4, extra_parents=prior_promoted(before_run=3))
p = Path("data/models/generator_metrics.json")
m = json.loads(p.read_text())
m["mutation"]["rollouts"] = mf["rollouts"]
p.write_text(json.dumps(m, indent=2, default=str))
print("rollouts", len(mf["rollouts"]), "survivors", len(mf["survivors"]))
