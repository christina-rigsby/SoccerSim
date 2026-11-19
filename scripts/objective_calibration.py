"""Objective calibration: success rate against the time allowed, to choose realistic objectives.

    python scripts/objective_calibration.py --teams library main_latest --situations 50

For each kind of objective it plays one long game per situation (against every scripted style)
and records *when* the objective was first achieved (or, for keep and protect, first failed), so
one game gives the success rate for every time limit up to its length:

- score: we score (from the final third);
- chance: an unblocked shot of xG >= 0.10 (from the final third or midfield);
- shot: any unblocked shot (from the final third or midfield);
- box: we complete a pass into their penalty area (from midfield);
- keep: we have not lost the ball (from our half or midfield);
- win_back: we have won the ball back (they have just won it deep in their half);
- protect: they have not scored (1-0 up, minute 85, they have the ball in our final third).

Writes reports/objectives/calibration/README.md: per kind, horizon and team, the overall rate and
the rate against the weakest style.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.evaluate_teams import expand  # noqa: E402

KINDS = {
    "score": {"types": ["final_third_attack"], "ours": True, "max_s": 180, "horizons": [30, 60, 120, 180]},
    "chance": {"types": ["final_third_attack", "mid_progression"], "ours": True, "max_s": 180,
               "horizons": [30, 60, 120, 180]},
    "shot": {"types": ["final_third_attack", "mid_progression"], "ours": True, "max_s": 120,
             "horizons": [15, 30, 60, 120]},
    "box": {"types": ["mid_progression"], "ours": True, "max_s": 120, "horizons": [15, 30, 60, 120]},
    "keep": {"types": ["build_up", "mid_progression"], "ours": True, "max_s": 60, "horizons": [10, 15, 20, 30, 60]},
    "win_back": {"types": ["transition_loss"], "ours": False, "max_s": 60, "horizons": [10, 15, 20, 30, 60]},
    "protect": {"types": ["final_third_attack"], "ours": False, "max_s": 300, "horizons": [60, 120, 180, 300],
                "score": (1, 0), "minute": 85.0},
}
INVERSE = ("keep", "protect")  # success = the failure event has not happened by the horizon


def first_time(kind: str, events: list[dict], side: int, t0: float) -> float | None:
    """Time (s from the start) of the first success event, or for keep/protect the first failure."""
    from soccersim.selfplay.rewards import shot_credit_xg

    them = 1 - side
    d = 1.0 if side == 0 else -1.0
    for e in events:
        t, team, ty = e["t"] - t0, e.get("team"), e["type"]
        if kind == "score" and ty == "goal" and team == side:
            return t
        if kind == "chance" and ty == "shot_taken" and team == side and shot_credit_xg(e) >= 0.10:
            return t
        if kind == "shot" and ty == "shot_taken" and team == side and (e.get("data") or {}).get("outcome") != "blocked":
            return t
        if kind == "box" and ty == "pass_completed" and team == side:
            x, y = e["pos"][0] * d, e["pos"][1]
            if x > 36.0 and abs(y) < 20.16:
                return t
        if kind == "keep" and ty == "possession_lost" and team == side:
            return t
        if kind == "win_back" and ty == "possession_won" and team == side:
            return t
        if kind == "protect" and ty == "goal" and team == them:
            return t
    return None


def jobs(teams: list[str], opps: list[str], n: int, seed: int) -> list[dict]:
    from soccersim.config import load_config
    from soccersim.selfplay.evaluate import team_spec

    forms = list(load_config("league")["formations"])
    specs = {t: team_spec(t) for t in {*teams, *opps}}
    out = []
    for kind, spec in KINDS.items():
        rng = np.random.default_rng([seed, list(KINDS).index(kind)])
        for k in range(n):
            side = k % 2
            f = (str(rng.choice(forms)), str(rng.choice(forms)))
            ours, theirs = spec.get("score", (0, 0))
            sc = {"type": str(rng.choice(spec["types"])), "attacking_team": side if spec["ours"] else 1 - side,
                  "home_formation": f[0], "away_formation": f[1],
                  "minute": float(spec.get("minute", rng.uniform(10, 85))),
                  "score": [ours, theirs] if side == 0 else [theirs, ours]}
            s = int(rng.integers(1 << 31))
            for t in teams:
                for o in opps:
                    home, away = (t, o) if side == 0 else (o, t)
                    out.append({"episode_id": f"C-{kind}-{t}-{o}-{k:04d}", "seed": s, "scenario": sc,
                                "home": {**specs[home], "id": home}, "away": {**specs[away], "id": away},
                                "randomise": True, "max_time_s": float(spec["max_s"]),
                                "stop_on_goal": kind in ("score", "protect"), "stop_on_turnover": False,
                                "keep_events": ["possession_won", "possession_lost", "pass_completed"],
                                "cal": {"kind": kind, "team": t, "opp": o, "k": k, "side": side}})
    return out


def main() -> int:
    from soccersim.selfplay.objectives import wilson
    from soccersim.selfplay.runner import run_jobs

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--teams", nargs="+", default=["library", "main_latest"])
    ap.add_argument("--opponents", nargs="+", default=["styles"])
    ap.add_argument("--situations", type=int, default=50)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--out", default=str(ROOT / "reports" / "objectives" / "calibration"))
    a = ap.parse_args()
    teams, opps = expand(a.teams), expand(a.opponents)
    js = jobs(teams, opps, a.situations, a.seed)
    tags = {j["episode_id"]: j["cal"] for j in js}
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    partial = out / "games.partial.jsonl"
    done = {}
    if partial.exists():
        for line in partial.read_text().splitlines():
            g = json.loads(line)
            done[g["episode_id"]] = g
    fh = open(partial, "a")  # noqa: SIM115

    def on_result(res: dict) -> None:
        eid = res["episode"]["episode_id"]
        tag = tags[eid]
        g = {**tag, "episode_id": eid, "t": first_time(tag["kind"], res.get("events", []), tag["side"], 0.0),
             "duration": res.get("duration")}
        done[eid] = g
        fh.write(json.dumps(g) + "\n")
        fh.flush()

    run_jobs([j for j in js if j["episode_id"] not in done], None, workers=a.workers, on_result=on_result,
             progress_every=1000)
    fh.close()
    games = list(done.values())
    lines = ["# Objective calibration: success rate against the time allowed\n",
             f"{a.situations} situations per kind, against every style ({', '.join(opps)}); "
             "`python scripts/objective_calibration.py`. Rate overall, and against the weakest style.\n",
             "| Objective | Within | " + " | ".join(teams) + " |", "|---|---|" + "---|" * len(teams)]
    for kind, spec in KINDS.items():
        for h in spec["horizons"]:
            cells = []
            for t in teams:
                per = {}
                for o in opps:
                    gs = [g for g in games if g["kind"] == kind and g["team"] == t and g["opp"] == o]
                    ok = [(g["t"] is None or g["t"] > h) if kind in INVERSE else (g["t"] is not None and g["t"] <= h)
                          for g in gs]
                    per[o] = (sum(ok), len(ok))
                k_all = sum(v[0] for v in per.values())
                n_all = sum(v[1] for v in per.values())
                weakest = min((v[0] / max(v[1], 1), o) for o, v in per.items())
                p, _, _ = wilson(k_all, n_all)
                cells.append(f"{p:.0%} (weakest {weakest[0]:.0%} v {weakest[1]})")
            lines.append(f"| {kind} | {h} s | " + " | ".join(cells) + " |")
    (out / "README.md").write_text("\n".join(lines) + "\n")
    (out / "games.json").write_text(json.dumps(games))
    partial.unlink(missing_ok=True)
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
