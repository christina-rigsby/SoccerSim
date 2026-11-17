"""Realism scorecard: how a team's games compare with real football (a diagnostic, not a target).

    python scripts/realism_report.py                       # best selector v every style, 28 x 5 min
    python scripts/realism_report.py --team lookahead_fast --games 12 --minutes 5

Plays continuous games (no stop at turnovers or goals) with full tracking and reports, per team
per 90 minutes, the measures below next to approximate real-football ranges (top-level men's
football; rough reference values, for spotting what to inspect, not for tuning towards). Pass
completion counts every pass played (completed, intercepted, lost on the first touch, out of play),
and is broken down by length and by pressure on the passer. Writes ``--out`` (JSON + README).
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from multiprocessing import get_context
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

#: Approximate real-football ranges (per team per 90 minutes unless stated).
REAL = {
    "passes": (450, 550), "pass_completion": (0.75, 0.85), "pass_completion_short": (0.85, 0.92),
    "pass_completion_long": (0.50, 0.62), "pressure_drop": (0.05, 0.15), "shots": (10, 15), "goals": (1.2, 1.6),
    "xg_per_shot": (0.09, 0.12), "tackles_won": (8, 15), "fouls": (9, 13), "ball_out_match": (70, 100),
    "distance_m_per_min": (105, 125), "share_above_4ms": (0.12, 0.20), "share_sprint": (0.01, 0.03),
    "top_speed": (8.5, 10.0), "shots_blocked_share": (0.20, 0.30),
    # Fatigue an outfield player builds up over 90 minutes (soccersim/sim/fatigue.py). Not a real
    # measurement: the law is set so that real work rates (105-125 m/min, little sprinting) would
    # give roughly 0.3-0.5; more running gives more.
    "fatigue_per_90": (0.3, 0.5),
}


def _game(job: dict) -> dict:
    import soccersim.sim.env as E
    from soccersim.schema import load_library
    from soccersim.selfplay.evaluate import team_spec
    from soccersim.selfplay.policies import make_policy
    from soccersim.sim.env import MatchEnv
    from soccersim.sim.scenarios import Scenario

    lib = load_library()
    passes: list[dict] = []
    orig = E.release

    def release(state, cmd, cfg, rng):
        p = state.ball.owner
        if p >= 0 and cmd.kind == "pass" and p // 11 == 0:
            opp = state.pos[11:22]
            passes.append({"len": float(np.hypot(*(np.asarray(cmd.target) - state.pos[p]))),
                           "press": float(np.min(np.linalg.norm(opp - state.pos[p], axis=1))),
                           "n_ev": len(state.events.events)})
        return orig(state, cmd, cfg, rng)

    E.release = release
    env = MatchEnv(randomise=True, record_frames=True)
    env.reset(job["seed"], Scenario())
    f0 = env.state.fatigue.copy()
    me = make_policy(team_spec(job["team"]), lib, np.random.default_rng(job["seed"] + 1))
    opp = make_policy(team_spec(job["opp"]), lib, np.random.default_rng(job["seed"] + 2))
    res = env.run(me, opp, max_time_s=job["seconds"], stop_on_goal=False, stop_on_turnover=False)
    E.release = orig
    evs = env.state.events.events
    for i, ps in enumerate(passes):
        end = passes[i + 1]["n_ev"] if i + 1 < len(passes) else len(evs)
        ps["ok"] = any(e.type == "pass_completed" and e.team == 0 for e in evs[ps["n_ev"]:end])
    ours = collections.Counter(e["type"] for e in res.events if e.get("team") == 0)
    outs = sum(1 for e in res.events if e["type"] == "ball_out")
    xg = [float((e.get("data") or {}).get("xg") or 0) for e in res.events
          if e["type"] == "shot_taken" and e["team"] == 0]
    pos = np.array([f["p"] for f in res.frames])
    sp = np.linalg.norm(np.diff(pos, axis=0), axis=2) * 10.0
    out_idx = [i for i in range(11) if env.state.kinds[i] != "GK"]
    sp_o = sp[:, out_idx]
    blocked = sum(1 for e in res.events if e["type"] == "shot_blocked" and e.get("team") == 1)
    fat = float(np.mean(env.state.fatigue[out_idx] - f0[out_idx]))
    return {"seconds": res.duration_s, "passes": passes, "ev": dict(ours), "outs": outs, "xg": xg,
            "dist_per_min": float(np.median(sp_o.sum(axis=0) / 10.0) / (res.duration_s / 60)),
            "above4": float((sp_o >= 4).mean()), "sprint": float((sp_o >= 7).mean()),
            "top_speed": float(np.percentile(sp_o, 99.9)), "blocked": blocked, "fatigue_gain": fat}


def report(team: str, games: int, minutes: float, workers: int, seed: int) -> dict:
    from soccersim.config import load_config

    styles = list(load_config("league")["scripted_styles"])
    jobs = [{"team": team, "opp": styles[k % len(styles)], "seed": seed + k, "seconds": minutes * 60}
            for k in range(games)]
    with get_context("fork").Pool(workers) as pool:
        rs = pool.map(_game, jobs)
    mins = sum(r["seconds"] for r in rs) / 60
    per90 = lambda n: n / mins * 90  # noqa: E731
    ps = [p for r in rs for p in r["passes"]]

    def comp(sel) -> float | None:
        s = [p for p in ps if sel(p)]
        return float(np.mean([p["ok"] for p in s])) if s else None

    ev = collections.Counter()
    for r in rs:
        ev.update(r["ev"])
    xg = [x for r in rs for x in r["xg"]]
    pressed, free = comp(lambda p: p["press"] < 2), comp(lambda p: p["press"] >= 4)
    m = {
        "passes": per90(len(ps)), "pass_completion": comp(lambda p: True),
        "pass_completion_short": comp(lambda p: p["len"] < 15), "pass_completion_long": comp(lambda p: p["len"] >= 30),
        "pressure_drop": (free - pressed) if pressed is not None and free is not None else None,
        "shots": per90(ev["shot_taken"]), "goals": per90(ev["goal"]), "xg_per_shot": float(np.mean(xg)) if xg else None,
        "tackles_won": per90(ev["tackle_won"]), "fouls": per90(ev["foul_won"]),
        "ball_out_match": per90(sum(r["outs"] for r in rs)),
        "distance_m_per_min": float(np.median([r["dist_per_min"] for r in rs])),
        "share_above_4ms": float(np.mean([r["above4"] for r in rs])),
        "share_sprint": float(np.mean([r["sprint"] for r in rs])),
        "top_speed": float(np.max([r["top_speed"] for r in rs])),
        "shots_blocked_share": sum(r["blocked"] for r in rs) / max(ev["shot_taken"], 1),
        "fatigue_per_90": float(np.mean([r["fatigue_gain"] / r["seconds"] for r in rs]) * 5400),
    }
    return {"team": team, "games": games, "minutes": mins, "measures": m}


def markdown(rep: dict) -> str:
    lines = [f"# Realism scorecard: `{rep['team']}`\n",
             f"{rep['games']} continuous games, {rep['minutes']:.0f} minutes against every scripted style. Per team "
             "per 90 minutes unless stated; real ranges are approximate (a diagnostic, not a target).\n",
             "| Measure | Simulation | Real (approx.) | |", "|---|---|---|---|"]
    for k, v in rep["measures"].items():
        lo, hi = REAL[k]
        pct = k.startswith(("pass_completion", "pressure_drop", "share_", "shots_blocked"))
        fmt = (lambda x: f"{x:.0%}") if pct else (lambda x: f"{x:.2f}" if x < 10 else f"{x:.0f}")
        flag = "" if v is None else ("ok" if lo <= v <= hi else ("high" if v > hi else "low"))
        lines.append(f"| {k} | {'—' if v is None else fmt(v)} | {fmt(lo)}–{fmt(hi)} | {flag} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--team", default="selector")
    ap.add_argument("--games", type=int, default=28)
    ap.add_argument("--minutes", type=float, default=5.0)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--seed", type=int, default=500)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    rep = report(a.team, a.games, a.minutes, a.workers, a.seed)
    out = Path(a.out or ROOT / "reports" / "realism" / a.team)
    out.mkdir(parents=True, exist_ok=True)
    (out / "realism.json").write_text(json.dumps(rep, indent=1))
    (out / "README.md").write_text(markdown(rep))
    print(markdown(rep))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
