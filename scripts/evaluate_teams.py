"""Evaluate teams reliably: many paired continuous games, with standard errors.

    python scripts/evaluate_teams.py --teams library library_critic selector --opponents styles
    python scripts/evaluate_teams.py --teams library selector --opponents held_out --scenarios 200
    python scripts/evaluate_teams.py --teams library --opponents styles --scenarios 20 --out reports/evaluation/smoke

``--opponents``: team names, or ``styles`` (every scripted style), ``training`` (styles used in
training) or ``held_out`` (styles never trained against). ``--baseline`` (default: the first
team) is the team every other team is compared with game by game. See
``soccersim/selfplay/evaluate.py`` for the design and measures. Writes ``README.md`` (tables),
``summary.json`` and ``games.json`` to ``--out``.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from soccersim.config import load_config  # noqa: E402
from soccersim.selfplay.evaluate import markdown, run_evaluation, save, summarise  # noqa: E402


def expand(names: list[str]) -> list[str]:
    lcfg = load_config("league")
    styles = list(lcfg["scripted_styles"])
    held = list(lcfg["held_out_styles"])
    out: list[str] = []
    for n in names:
        out += {"styles": styles, "held_out": held, "training": [s for s in styles if s not in held]}.get(n, [n])
    return list(dict.fromkeys(out))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--teams", nargs="+", required=True)
    ap.add_argument("--opponents", nargs="+", default=["styles"])
    ap.add_argument("--scenarios", type=int, default=100, help="scenarios per pairing (each played from both sides)")
    ap.add_argument("--max-time", type=float, default=120.0, help="seconds of play per game")
    ap.add_argument("--baseline", default=None)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--seed", type=int, default=2024)
    ap.add_argument("--models", default=str(ROOT / "data" / "models"))
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    teams, opps = expand(a.teams), expand(a.opponents)
    n_games = a.scenarios * 2 * sum(1 for t in teams for o in opps if o != t)
    print(f"{len(teams)} teams x {len(opps)} opponents x {a.scenarios} scenarios x 2 sides = {n_games} games",
          flush=True)
    t0 = time.time()
    ev = run_evaluation(teams, opps, a.scenarios, a.workers, a.seed, a.max_time, a.models)
    summ = summarise(ev, a.baseline or teams[0])
    out = save(ev, summ, a.out or ROOT / "reports" / "evaluation" / time.strftime("%Y%m%d-%H%M"))
    print(markdown(ev, summ))
    print(f"wrote {out} ({time.time() - t0:.0f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
