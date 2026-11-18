"""Expert iteration for an objective: search with the objective-driven look-ahead, distil, repeat.

    python scripts/expert.py --objective keep_30 --games 400 --iterations 2

See soccersim/selfplay/expert.py. Resumable: finished chunks and iterations are skipped. Evaluate
the networks with scripts/objectives.py (teams ``expert@objective``, ``expert0@objective``, ...).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from soccersim.selfplay.expert import run  # noqa: E402
from soccersim.selfplay.objectives import OBJECTIVES  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--objective", nargs="+", required=True, choices=list(OBJECTIVES))
    ap.add_argument("--games", type=int, default=400, help="search games per iteration")
    ap.add_argument("--iterations", type=int, default=2)
    ap.add_argument("--epochs", type=int, default=12)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--models", default=str(ROOT / "data" / "models"))
    a = ap.parse_args()
    for obj in a.objective:
        for r in run(obj, a.games, a.iterations, a.workers, a.models, ROOT / "data", a.epochs):
            last = r["history"][-1]
            print(f"{obj} iteration {r['iteration']}: {r['decisions']} decisions; picks the search's best "
                  f"{last['top1']:.1%} (base {last['top1_score']:.1%}, chance {last['top1_chance']:.1%})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
