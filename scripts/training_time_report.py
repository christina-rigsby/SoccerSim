"""Training-time report: how long each team takes to train, in games and in wall-clock time.

    python scripts/training_time_report.py                      # current pool, writes reports/training_time/

For the current opponent pool it reads the logged games (data/<pool data>/run=*/episodes-*.parquet)
and the pipeline log (data/pipeline_v<N>.log), and reports for each team:

- **selector**: the library games every learned team starts from (Phase A), the critic trained on
  them, and the selector's own refinement rounds (games it plays itself, then refits);
- **generator** (the main agent): the same Phase A games and critic, then pretraining (behaviour
  cloning on library plays and screening mutated plays by short trial games) and the league (PPO
  updates in self-play games);
- **look-ahead**: no training at all; it pays at game time instead, simulating every candidate
  play before each decision. Its cost is measured as wall-clock time per game, next to the others.

Game durations are simulated seconds (training games are scenario games, not full matches: they
end at a goal or a change of possession). Wall-clock stage times come from the pipeline log; a
stage interrupted by a machine restart counts only its final, uninterrupted run.
"""

from __future__ import annotations

import argparse
import glob
import json
import re
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from soccersim.config import load_config  # noqa: E402

BINS = [0, 5, 10, 20, 30, 60, 120, 1e9]


def durations(run_glob: str) -> np.ndarray:
    import pyarrow.parquet as pq

    files = sorted(glob.glob(run_glob, recursive=True))
    out = [pq.read_table(f, columns=["duration_s"]).column("duration_s").to_numpy() for f in files]
    return np.concatenate(out) if out else np.zeros(0)


def stage_times(log: Path) -> dict[str, float]:
    """Seconds of each stage's last uninterrupted run (start -> done)."""
    starts, out = {}, {}
    for line in log.read_text().splitlines():
        m = re.match(r"== (\w+): (start|done) (\d\d):(\d\d):(\d\d)", line)
        if not m:
            continue
        s = int(m[3]) * 3600 + int(m[4]) * 60 + int(m[5])
        if m[2] == "start":
            starts[m[1]] = s
        elif m[1] in starts:
            out[m[1]] = (s - starts[m[1]]) % 86400
    return out


def per_game_wall(teams: list[str], n: int = 8, seconds: float = 120.0) -> dict[str, float]:
    """Wall-clock seconds to play one 120-second game, per team (one core, same scenarios)."""
    from soccersim.schema import load_library
    from soccersim.selfplay.evaluate import team_spec
    from soccersim.selfplay.policies import make_policy
    from soccersim.sim.env import MatchEnv
    from soccersim.sim.scenarios import Scenario

    lib = load_library()
    out = {}
    for t in teams:
        t0 = time.time()
        for k in range(n):
            env = MatchEnv(randomise=True, record_frames=False)
            env.reset(500 + k, Scenario(type="mid_progression", attacking_team=k % 2))
            me = make_policy(team_spec(t), lib, np.random.default_rng(k))
            op = make_policy(team_spec("library"), lib, np.random.default_rng(k + 9))
            pols = (me, op) if k % 2 == 0 else (op, me)
            env.run(*pols, max_time_s=seconds, stop_on_goal=False, stop_on_turnover=False)
        out[t] = (time.time() - t0) / n
    return out


def dist_row(d: np.ndarray) -> str:
    if len(d) == 0:
        return "— | — | —"
    h, _ = np.histogram(d, BINS)
    shares = " / ".join(f"{100 * x / len(d):.0f}%" for x in h)
    return (f"{np.median(d):.1f} s | {np.percentile(d, 10):.1f}–{np.percentile(d, 90):.1f} s | {shares}")


def fmt_h(s: float) -> str:
    return f"{s / 3600:.1f} h" if s >= 3600 else f"{s / 60:.0f} min"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(ROOT / "reports" / "training_time"))
    ap.add_argument("--games", type=int, default=8, help="games per team for the per-game cost")
    a = ap.parse_args()
    lcfg = load_config("league")
    v = lcfg.get("pool_version", 1)
    data = ROOT / lcfg["data"]["selfplay"]
    st = stage_times(ROOT / "data" / f"pipeline_v{v}.log")
    groups = {
        "Phase A (library games, shared)": durations(str(data / "run=phase_a" / "**" / "episodes-*.parquet")),
        "Selector refinement rounds": durations(str(data / "run=selector_*" / "**" / "episodes-*.parquet")),
        "Generator league (PPO)": durations(str(data / "run=league_*" / "**" / "episodes-*.parquet")),
    }
    wall = per_game_wall(["library", "selector_latest", "main_latest", "lookahead_fast@score_120"], a.games)
    shared = st.get("phase_a", 0) + st.get("critic", 0)
    sel = shared + st.get("selector", 0)
    gen = shared + st.get("pretrain", 0) + st.get("league", 0)
    n_a, n_s, n_l = (len(groups[k]) for k in groups)
    lines = [
        "# Training time\n",
        f"Opponent pool v{v} (the current one), measured from the logged games and the pipeline log "
        "(`python scripts/training_time_report.py`). Wall-clock times are on this machine (4 cores); a stage "
        "interrupted by a machine restart counts only its final, uninterrupted run. Game durations are "
        "simulated seconds: training games are scenario games that end at a goal or a change of possession.\n",
        "## Per team\n",
        "| Team | What its training is | Games played | Training wall-clock time |",
        "|---|---|---|---|",
        f"| Selector | Phase A library games → critic → {n_s // 300 if n_s else 0} refinement rounds of its own games "
        f"| {n_a + n_s:,} ({n_a:,} Phase A + {n_s:,} own) | {fmt_h(sel)} (Phase A {fmt_h(st.get('phase_a', 0))}, "
        f"critic {fmt_h(st.get('critic', 0))}, rounds {fmt_h(st.get('selector', 0))}) |",
        f"| Generator (main agent) | Phase A games → critic → pretraining (behaviour cloning + screening "
        f"mutated plays in short trial games) → league | {n_a + n_l:,} ({n_a:,} Phase A + {n_l:,} league) "
        f"+ the screening trials | {fmt_h(gen)} (Phase A {fmt_h(st.get('phase_a', 0))}, critic "
        f"{fmt_h(st.get('critic', 0))}, pretraining {fmt_h(st.get('pretrain', 0))}, league "
        f"{fmt_h(st.get('league', 0))}) |",
        "| Look-ahead | none: it simulates candidate plays during the game | 0 | 0 |",
        "",
        "## Game durations (simulated seconds)\n",
        "| Games | Number | Median | 10th–90th percentile | Share in 0–5 / 5–10 / 10–20 / 20–30 / 30–60 / "
        "60–120 / 120+ s |",
        "|---|---|---|---|---|",
    ]
    for k, d in groups.items():
        lines.append(f"| {k} | {len(d):,} | {dist_row(d)} |")
    lines += ["", "## Cost when playing (wall-clock seconds per 120-second game, one core)\n",
              "| Team | Seconds per game | Relative to the library |", "|---|---|---|"]
    for t, s in wall.items():
        lines.append(f"| {t} | {s:.1f} | {s / wall['library']:.1f}x |")
    (Path(a.out)).mkdir(parents=True, exist_ok=True)
    (Path(a.out) / "README.md").write_text("\n".join(lines) + "\n")
    (Path(a.out) / "training_time.json").write_text(json.dumps(
        {"stages_s": st, "games": {k: len(d) for k, d in groups.items()},
         "durations": {k: [float(x) for x in np.percentile(d, [10, 50, 90])] if len(d) else None
                       for k, d in groups.items()}, "per_game_wall_s": wall}, indent=1))
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
