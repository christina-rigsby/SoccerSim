"""Train a critic on the look-ahead team's trials (soccersim/selfplay/trial_critic.py).

    python scripts/trial_critic.py generate --games 800 [--horizon 12] [--base selector]
    python scripts/trial_critic.py train                                     # -> data/models/trial_critic/
    python scripts/evaluate_teams.py --teams selector trial_critic --opponents styles --scenarios 20
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from soccersim.selfplay import trial_critic  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate")
    g.add_argument("--games", type=int, default=800)
    g.add_argument("--workers", type=int, default=4)
    g.add_argument("--max-time", type=float, default=60.0)
    g.add_argument("--base", default=None, help="build the look-ahead on this team (e.g. selector)")
    g.add_argument("--horizon", type=float, default=12.0, help="seconds each trial plays forward")
    t = sub.add_parser("train")
    t.add_argument("--epochs", type=int, default=12)
    a = ap.parse_args()
    if a.cmd == "generate":
        print(trial_critic.generate(a.games, a.workers, max_time_s=a.max_time, base=a.base, horizon_s=a.horizon))
    else:
        trial_critic.train(epochs=a.epochs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
