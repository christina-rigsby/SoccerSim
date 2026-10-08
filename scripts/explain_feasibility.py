"""Explain, play by play, why each play is or is not feasible in one game situation.

    python scripts/explain_feasibility.py                         # mid_progression, seed 0, t = 0
    python scripts/explain_feasibility.py --scenario build_up --seed 3 --at 4.0
    python scripts/explain_feasibility.py --play fullback_outlet_bounce --detail

It sets up a scenario, optionally plays it for ``--at`` seconds with library teams, then runs
exactly the checks Module 2 runs (``RankingPolicy.rank`` -> ``evaluate``, in
``soccersim/ranking/selector.py``) for the team with the ball (or ``--team``) and prints, for
every play: phase, cooldown, role assignment (who would play each role, or why nobody can),
every trigger and hard-constraint condition with its true/false value, and the score of the
feasible plays. See docs/PLAY_FEASIBILITY.md for what each check means.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from soccersim.dashboard.evaluator import Evaluator  # noqa: E402
from soccersim.dashboard.team_state import TeamView  # noqa: E402
from soccersim.ranking.assignment import assign  # noqa: E402
from soccersim.ranking.constraints import ATTACK_PHASES as ATTACK  # noqa: E402
from soccersim.ranking.constraints import phases_for  # noqa: E402
from soccersim.ranking.scorer import score_play  # noqa: E402
from soccersim.ranking.selector import RankingPolicy  # noqa: E402
from soccersim.schema import load_library  # noqa: E402
from soccersim.sim.env import MatchEnv  # noqa: E402
from soccersim.sim.restarts import execute_restart  # noqa: E402
from soccersim.sim.scenarios import SCENARIO_TYPES, Scenario  # noqa: E402

OK, NO = "yes", "NO "


def _conditions(pred, ev: Evaluator, neg: bool = False, any_of: bool = False) -> list[tuple[str, bool]]:
    """Each condition with its outcome as the play needs it: ``not`` is folded into the label,
    and conditions inside an ``any:`` group (only one of which must hold) are marked."""
    if pred == "always":
        return []
    (key, body), = pred.items()
    if key in ("all", "any") and isinstance(body, list):
        out = []
        for sub in body:
            out += _conditions(sub, ev, neg, any_of or key == "any")
        return out
    if key == "not":
        return _conditions(body, ev, not neg, any_of)
    val = ev.pred({key: body}) != neg
    label = ("not " if neg else "") + _fmt(key, body) + ("   (one of an any: group)" if any_of else "")
    return [(label, val)]


def _fmt(key: str, body) -> str:
    return f"{key}: {json.dumps(body, separators=(',', ':'))}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenario", default="mid_progression", choices=SCENARIO_TYPES)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--at", type=float, default=0.0, help="play this many seconds first (library teams)")
    ap.add_argument("--team", type=int, default=None, help="0 or 1 (default: the team with the ball)")
    ap.add_argument("--play", default=None, help="only this play")
    ap.add_argument("--detail", action="store_true", help="every condition, not only the first failing one")
    a = ap.parse_args()

    lib = load_library()
    env = MatchEnv(randomise=False, record_frames=False)
    env.reset(a.seed, Scenario(type=a.scenario, attacking_team=0))
    if env.state.restart is not None:
        execute_restart(env.state, env.cfg)
    if a.at > 0:
        rng = np.random.default_rng(a.seed)
        env.run(RankingPolicy(lib, rng=rng), RankingPolicy(lib, rng=rng), max_time_s=a.at,
                stop_on_goal=False, stop_on_turnover=False)
    st = env.state
    team = a.team if a.team is not None else (st.possession if st.possession is not None else 0)
    view = TeamView(st, team, env.ctx)
    pol = RankingPolicy(lib)
    side = view.side_from_ball()
    phases = phases_for(view)
    print(f"scenario {a.scenario}, seed {a.seed}, t = {st.t:.1f} s; team {team} "
          f"({'has' if view.possession == 'us' else 'does not have'} the ball); ball at "
          f"({view.ball[0]:.1f}, {view.ball[1]:.1f}) in its attacking frame; ball side "
          f"{'+y' if side > 0 else '-y'}; phases checked: {', '.join(phases) or 'none (loose ball)'}")
    print("legend: 1 phase  2 cooldown  3 roles (assignment)  4 triggers  5 hard constraints  -> score\n")
    rows = []
    for play in lib.values():
        if a.play and play.id != a.play:
            continue
        out = [f"{play.id}  [{play.phase}]"]
        if play.phase not in phases:
            need = "the ball" if play.phase in ATTACK else "to be without the ball"
            out.append(f"  1 phase      {NO} the team needs {need}")
            rows.append((0, out))
            continue
        out.append(f"  1 phase      {OK}")
        out.append(f"  2 cooldown   {OK} (fresh policy; cooldowns only exist mid-game)")
        asg = assign(play, view, side, pol.cfg)
        if not asg.feasible:
            out.append(f"  3 roles      {NO} {asg.reason}")
            rows.append((1, out))
            continue
        bind = ", ".join(f"{r}={'/'.join(str(p) for p in ps)}({view.hint_of(ps[0], side)})"
                         for r, ps in asg.binding.items() if ps)
        out.append(f"  3 roles      {OK} {bind}")
        ev = Evaluator(view, asg.binding, side, event_default_tick=view.tick, play_start_t=view.t, step_start_t=view.t)
        trig_ok = ev.pred(play.triggers)
        out.append(f"  4 triggers   {OK if trig_ok else NO}")
        for label, val in _conditions(play.triggers, ev):
            if a.detail or not val:
                out.append(f"       {'met    ' if val else 'NOT met'}  {label}")
        if not trig_ok:
            rows.append((2, out))
            continue
        hc_fail = [i for i, hc in enumerate(play.hard_constraints) if not ev.pred(hc)]
        out.append(f"  5 hard       {OK if not hc_fail else NO}" + ("" if play.hard_constraints else " (none)"))
        for i, hc in enumerate(play.hard_constraints):
            for label, val in _conditions(hc, ev):
                if a.detail or i in hc_fail:
                    out.append(f"       {'met    ' if val else 'NOT met'}  {label}")
        if hc_fail:
            rows.append((3, out))
            continue
        score, comp = score_play(play, view, asg, pol.cfg)
        out.append(f"  -> FEASIBLE, score {score:+.4f}  " + " ".join(f"{k} {v:+.4f}" for k, v in comp.items() if v))
        rows.append((4, out))
    for _, out in sorted(rows, key=lambda r: -r[0]):
        print("\n".join(out))
        print()
    feas = sum(1 for k, _ in rows if k == 4)
    print(f"{feas} of {len(rows)} plays feasible.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
