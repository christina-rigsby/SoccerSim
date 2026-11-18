"""Objective success rates: how often each team achieves objectives chosen in advance.

    python scripts/objectives.py --teams library selector --scenarios 200
    python scripts/objectives.py --teams library lookahead_fast --objectives score_30 protect_60 \\
        --conditions fresh our_forwards_slow --scenarios 100 --out reports/objectives/smoke

``--opponents``: team names, or ``styles`` (every scripted style, the default). See
soccersim/selfplay/objectives.py for the objectives, conditions and measures. Writes README.md,
summary.json and games.json to ``--out``; an interrupted run resumes from ``--out``/games.partial.jsonl,
and a finished one is skipped (``--force`` runs it again).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.evaluate_teams import expand  # noqa: E402
from soccersim.selfplay.objectives import CONDITIONS, OBJECTIVES, markdown, run, summarise  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--teams", nargs="+", required=True)
    ap.add_argument("--opponents", nargs="+", default=["styles"])
    ap.add_argument("--objectives", nargs="+", default=list(OBJECTIVES), choices=list(OBJECTIVES))
    ap.add_argument("--conditions", nargs="+", default=["fresh"], choices=list(CONDITIONS))
    ap.add_argument("--scenarios", type=int, default=200, help="situations per objective")
    ap.add_argument("--baseline", default="library")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--models", default=str(ROOT / "data" / "models"))
    ap.add_argument("--out", default=None)
    ap.add_argument("--force", action="store_true", help="run again even if --out already has a finished report")
    a = ap.parse_args()
    teams, opps = expand(a.teams), expand(a.opponents)
    out = Path(a.out or ROOT / "reports" / "objectives" / time.strftime("%Y%m%d-%H%M"))
    if (out / "README.md").exists() and not a.force:
        print(f"{out} is already finished (README.md); skipping (--force to run again)")
        return 0
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    partial = out / "games.partial.jsonl"
    games = run(teams, opps, a.objectives, a.scenarios, a.conditions, a.workers, a.seed, a.models, partial)
    summ = summarise(games, a.baseline)
    (out / "games.json").write_text(json.dumps(games))
    (out / "summary.json").write_text(json.dumps({**summ, "args": vars(a)}, indent=1))
    (out / "README.md").write_text(markdown(summ, a.scenarios))
    partial.unlink(missing_ok=True)
    print(markdown(summ, a.scenarios))
    print(f"wrote {out} ({time.time() - t0:.0f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
