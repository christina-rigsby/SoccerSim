"""Objectives: chosen goals for a situation, and how often a team achieves them.

Success here is achieving an objective named in advance ("score within 30 seconds", "protect
the lead for a minute"), not winning on average. An objective is a kind of situation plus a test
of the game that follows (:data:`OBJECTIVES`):

Current objectives (D-063, chosen from reports/objectives/calibration so that high success is
realistic; targets in :data:`TARGETS`, against the weakest style):

=============  ===============================================================  =========
objective      situation (our side)                                             success
=============  ===============================================================  =========
shot_60        we have the ball in the final third or midfield                  an unblocked shot in 60 s
keep_15        we have the ball in our half or midfield                         no loss of the ball in 15 s
win_back_20    they have just won the ball deep in their own half               we win it back in 20 s
protect_300    1-0 up, minute 85, they have the ball in our final third         no goal against in 5 min
chance_180     we have the ball in the final third or midfield                  unblocked shot, xG >= 0.10, 3 min
score_180      we have the ball in the final third                              we score in 3 min (no target)
=============  ===============================================================  =========

Earlier sets (D-057, D-059) are kept for comparison with their reports. Keep and win-back games end
shortly after the first change of possession, which decides them.

**Conditions** test adaptivity: capabilities that differ from the usual or change during the
situation, through ``Scenario.cap_events`` (soccersim/sim/fatigue.py):

- ``fresh``: no changes (players still carry the fatigue of the match minute);
- ``our_forwards_slow``: our forwards (ST, W, AM) are replaced at the start by slow substitutes
  (pace and acceleration 0.25);
- ``their_defence_tiring``: their defenders (CB, FB) lose pace and acceleration (down to 0.25)
  over the first 15 s of the situation.

**Objective-driven play.** A look-ahead team named ``<team>@objective`` (e.g.
``lookahead_fast@objective``) is told the objective of each situation and scores its trials by it
(:func:`trial_value`).

**Measurement.** Each objective uses ``n`` fixed situations (the same for every team), played
against every opponent; the evaluated team alternates home and away by situation. A rate is
reported with its 95% Wilson interval; the headline for a team and objective is its rate against
its *weakest* opponent (the worst style), and "beats the library" means beating the library's rate
against every opponent. Results against different styles are correlated (in the same situation
the styles often choose the same plays at first, especially when defending), so the interval of a
rate pooled over styles is too narrow; judge by the per-opponent rates, each from ``n`` situations.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from ..config import load_config
from .evaluate import team_spec

#: name -> situation (scenario types, whose ball, score from our side, minute) and test.
OBJECTIVES: dict[str, dict[str, Any]] = {
    # Current set (D-063): chosen from the calibration (reports/objectives/calibration) so that high
    # success rates are realistic; targets in TARGETS.
    "shot_60": {"kind": "shot", "types": ["final_third_attack", "mid_progression"], "ours": True,
                "seconds": 60.0},
    "keep_15": {"kind": "keep", "types": ["build_up", "mid_progression"], "ours": True, "seconds": 15.0,
                "stop_on_turnover": True},
    "win_back_20": {"kind": "win_back", "types": ["transition_loss"], "ours": False, "seconds": 20.0,
                    "stop_on_turnover": True},
    "protect_300": {"kind": "protect", "types": ["final_third_attack"], "ours": False, "seconds": 300.0,
                    "score": (1, 0), "minute": 85.0},
    "chance_180": {"kind": "chance", "types": ["final_third_attack", "mid_progression"], "ours": True,
                   "seconds": 180.0, "min_xg": 0.10, "unblocked": True},
    "score_180": {"kind": "score", "types": ["final_third_attack"], "ours": True, "seconds": 180.0},
    # Second set (D-059; reports/objectives/baseline_pool_v8), kept for comparison.
    "score_120": {"kind": "score", "types": ["final_third_attack"], "ours": True, "seconds": 120.0},
    "chance_60": {"kind": "chance", "types": ["final_third_attack", "mid_progression"], "ours": True,
                  "seconds": 60.0, "min_xg": 0.10, "unblocked": True},
    "keep_30": {"kind": "keep", "types": ["build_up", "mid_progression"], "ours": True, "seconds": 30.0,
                "stop_on_turnover": True},
    "win_back_30": {"kind": "win_back", "types": ["transition_loss"], "ours": False, "seconds": 30.0,
                    "stop_on_turnover": True},
    "protect_180": {"kind": "protect", "types": ["final_third_attack"], "ours": False, "seconds": 180.0,
                    "score": (1, 0), "minute": 85.0},
    # First set (D-057; reports/objectives/baseline_pool_v6), kept for comparison.
    "score_30": {"kind": "score", "types": ["final_third_attack"], "ours": True, "seconds": 30.0},
    "chance_30": {"kind": "chance", "types": ["final_third_attack"], "ours": True, "seconds": 30.0, "min_xg": 0.10},
    "protect_60": {"kind": "protect", "types": ["final_third_attack", "mid_progression"], "ours": False,
                   "seconds": 60.0, "score": (1, 0), "minute": 80.0},
    "win_back_8": {"kind": "win_back", "types": ["transition_loss"], "ours": False, "seconds": 8.0},
}
CURRENT = ("shot_60", "keep_15", "win_back_20", "protect_300", "chance_180", "score_180")
#: Agreed targets (D-063): success rate against the weakest style, and beating the library against every
#: style. score_180 is reported without a target (no realistic definition of scoring reaches a high rate).
TARGETS = {"shot_60": 0.90, "keep_15": 0.75, "win_back_20": 0.75, "protect_300": 0.90, "chance_180": 0.60}
CONDITIONS = ("fresh", "our_forwards_slow", "their_defence_tiring")
EVENTS = ("possession_won", "possession_lost", "substitution")


def _kinds(formation: str) -> list[str]:
    spec = load_config("formations")["formations"][formation]
    return [s["kind"] for s in spec.values()]


def cap_events(condition: str, our_side: int, formations: tuple[str, str]) -> list[dict[str, Any]]:
    """Scenario capability changes for ``condition`` (player indices for our side ``our_side``)."""
    if condition == "fresh":
        return []
    slow = {"pace": 0.25, "acceleration": 0.25}
    if condition == "our_forwards_slow":
        side, kinds, ev = our_side, ("ST", "W", "AM"), {"t": 0.0, "substitute": True, "caps": slow}
    elif condition == "their_defence_tiring":
        side, kinds, ev = 1 - our_side, ("CB", "FB"), {"t": 0.0, "ramp_s": 15.0, "caps": slow}
    else:
        raise ValueError(f"unknown condition {condition!r}; one of {CONDITIONS}")
    return [{**ev, "player": side * 11 + i} for i, k in enumerate(_kinds(formations[side])) if k in kinds]


def situations(objective: str, n: int, seed: int = 7) -> list[dict[str, Any]]:
    """``n`` fixed situations for ``objective``: scenario fields from our side, and a game seed."""
    spec = OBJECTIVES[objective]
    forms = list(load_config("league")["formations"])
    rng = np.random.default_rng([seed, sorted(OBJECTIVES).index(objective)])
    out = []
    for k in range(n):
        out.append({"type": str(rng.choice(spec["types"])), "our_formation": str(rng.choice(forms)),
                    "their_formation": str(rng.choice(forms)),
                    "minute": float(spec.get("minute", rng.uniform(10, 85))),
                    "seed": int(rng.integers(1 << 31)), "our_side": k % 2})
    return out


def build_jobs(teams: list[str], opponents: list[str], objectives: list[str], n: int, conditions: list[str],
               seed: int = 7, models_dir: str | Path = "data/models") -> list[dict[str, Any]]:
    # A team named "<look-ahead team>@objective" plays for whichever objective is being measured.
    named = {(t, obj): t.replace("@objective", f"@{obj}") for t in teams for obj in objectives}
    specs = {n: team_spec(n, models_dir) for n in {*named.values(), *opponents}}
    jobs = []
    for obj in objectives:
        spec = OBJECTIVES[obj]
        for k, s in enumerate(situations(obj, n, seed)):
            side = s["our_side"]
            forms = (s["our_formation"], s["their_formation"]) if side == 0 else (s["their_formation"],
                                                                               s["our_formation"])
            ours, theirs = spec.get("score", (0, 0))
            score = (ours, theirs) if side == 0 else (theirs, ours)
            for cond in conditions:
                scen = {"type": s["type"], "attacking_team": side if spec["ours"] else 1 - side,
                        "home_formation": forms[0], "away_formation": forms[1], "minute": s["minute"],
                        "score": list(score), "cap_events": cap_events(cond, side, forms)}
                for t in teams:
                    for o in opponents:
                        if o == t:
                            continue
                        me = named[(t, obj)]
                        home, away = (me, o) if side == 0 else (o, me)
                        jobs.append({"episode_id": f"O-{obj}-{cond}-{t}-{o}-{k:04d}", "seed": s["seed"],
                                     "scenario": scen, "home": {**specs[home], "id": home},
                                     "away": {**specs[away], "id": away}, "randomise": True,
                                     "max_time_s": spec["seconds"], "stop_on_goal": True,
                                     # keep / win back: the outcome is decided at the first change
                                     # of possession, so the game ends shortly after it
                                     "stop_on_turnover": bool(spec.get("stop_on_turnover", False)),
                                     "keep_events": list(EVENTS),
                                     "obj": {"objective": obj, "condition": cond, "team": t, "opp": o, "k": k,
                                             "side": side}})
    return jobs


def success(objective: str, events: list[dict[str, Any]], side: int) -> bool:
    """Whether the game (its events, from our side ``side``) achieved ``objective``."""
    from .rewards import shot_credit_xg

    spec = OBJECTIVES[objective]
    kind, them = spec["kind"], 1 - side
    if kind == "score":
        return any(e["type"] == "goal" and e.get("team") == side for e in events)
    if kind == "chance":  # a shot of xG >= min_xg (not blocked, for objectives marked "unblocked")
        xg = shot_credit_xg if spec.get("unblocked") else (lambda e: float((e.get("data") or {}).get("xg") or 0.0))
        return any(e["type"] == "shot_taken" and e.get("team") == side and xg(e) >= spec["min_xg"] for e in events)
    if kind == "shot":  # any shot that was not blocked
        return any(e["type"] == "shot_taken" and e.get("team") == side
                   and (e.get("data") or {}).get("outcome") != "blocked" for e in events)
    if kind == "protect":
        return not any(e["type"] == "goal" and e.get("team") == them for e in events)
    if kind == "keep":
        return not any(e["type"] == "possession_lost" and e.get("team") == side for e in events)
    if kind == "win_back":
        return any(e["type"] == "possession_won" and e.get("team") == side for e in events)
    raise ValueError(objective)


def trial_value(objective: str, events: list[dict[str, Any]], team: int, depv: float, t0: float,
                horizon_s: float) -> float:
    """How well one look-ahead trial served ``objective`` (higher is better), for objective-driven
    play (soccersim/ranking/lookahead.py). The objective's own success, partly credited by timing,
    plus a small share of the change in expected possession value (EPV) to separate trials in
    which nothing decisive happened:

    - score_30: goals for (1 each) + xG of our shots - goals against;
    - chance_30: shots of xG >= 0.10 (1 each) + xG of our shots - goals against;
    - protect_60: - goals against - xG of their shots;
    - keep_30: 1 if we never lose the ball, else the share of the horizon before we lost it;
    - win_back_8: 1 - (time to win the ball back) / horizon if we win it back, else 0; - goals against.
    """
    them = 1 - team
    gf = sum(1 for e in events if e["type"] == "goal" and e.get("team") == team)
    ga = sum(1 for e in events if e["type"] == "goal" and e.get("team") == them)
    from .rewards import shot_credit_xg

    shots = [(e.get("team"), shot_credit_xg(e)) for e in events if e["type"] == "shot_taken"]  # blocked: 0
    xgf = sum(x for t, x in shots if t == team)
    xga = sum(x for t, x in shots if t == them)
    shaping = 0.2 * depv
    kind = OBJECTIVES[objective]["kind"]
    if kind == "score":
        return gf + xgf - ga + shaping
    if kind == "chance":
        good = sum(1 for t, x in shots if t == team and x >= OBJECTIVES[objective]["min_xg"])
        return good + xgf - ga + shaping
    if kind == "shot":
        unblocked = sum(1 for e in events if e["type"] == "shot_taken" and e.get("team") == team
                        and (e.get("data") or {}).get("outcome") != "blocked")
        return min(unblocked, 1) + xgf - ga + shaping
    if kind == "protect":
        return -ga - xga + shaping
    if kind == "keep":
        lost = [e["t"] for e in events if e["type"] == "possession_lost" and e.get("team") == team and e["t"] >= t0]
        return (1.0 if not lost else min(1.0, (min(lost) - t0) / horizon_s)) + shaping
    if kind == "win_back":
        won = [e["t"] for e in events if e["type"] == "possession_won" and e.get("team") == team and e["t"] >= t0]
        return (1.0 - min(1.0, (min(won) - t0) / horizon_s) if won else 0.0) - ga + shaping
    raise ValueError(objective)


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float, float]:
    """Rate and 95% Wilson interval."""
    if n == 0:
        return float("nan"), 0.0, 1.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return p, max(0.0, c - h), min(1.0, c + h)


def run(teams: list[str], opponents: list[str], objectives: list[str], n: int, conditions: list[str],
        workers: int = 4, seed: int = 7, models_dir: str | Path = "data/models",
        partial: str | Path | None = None, progress_every: int = 500) -> list[dict[str, Any]]:
    """Play every job (resuming from ``partial``, a JSONL file of finished games) and return the games."""
    from .runner import run_jobs

    jobs = build_jobs(teams, opponents, objectives, n, conditions, seed, models_dir)
    tags = {j["episode_id"]: j["obj"] for j in jobs}
    games: list[dict[str, Any]] = []
    done: set[str] = set()
    if partial is not None and Path(partial).exists():
        for line in Path(partial).read_text().splitlines():
            if line.strip():
                g = json.loads(line)
                if g.get("episode_id") in tags and g["episode_id"] not in done:
                    games.append(g)
                    done.add(g["episode_id"])
        print(f"  resuming: {len(done)} of {len(jobs)} games already played", flush=True)
    fh = open(partial, "a") if partial is not None else None  # noqa: SIM115

    def on_result(res: dict) -> None:
        eid = res["episode"]["episode_id"]
        tag = tags[eid]
        g = {**tag, "success": success(tag["objective"], res.get("events", []), tag["side"]),
             "seconds": res.get("duration"), "episode_id": eid}
        games.append(g)
        if fh is not None:
            fh.write(json.dumps(g) + "\n")
            fh.flush()

    try:
        run_jobs([j for j in jobs if j["episode_id"] not in done], None, workers=workers, on_result=on_result,
                 progress_every=progress_every)
    finally:
        if fh is not None:
            fh.close()
    return games


def summarise(games: list[dict[str, Any]], baseline: str = "library") -> dict[str, Any]:
    """Rates per (objective, condition, team, opponent), the weakest-opponent headline, and whether
    each team beats ``baseline`` against every opponent."""
    cells: dict[tuple, list[bool]] = {}
    for g in games:
        cells.setdefault((g["objective"], g["condition"], g["team"], g["opp"]), []).append(bool(g["success"]))
    rows = []
    for (obj, cond, t, o), v in sorted(cells.items()):
        p, lo, hi = wilson(sum(v), len(v))
        rows.append({"objective": obj, "condition": cond, "team": t, "opp": o, "n": len(v), "rate": p,
                     "lo": lo, "hi": hi})
    head = []
    keys = sorted({(r["objective"], r["condition"], r["team"]) for r in rows})
    by = {(r["objective"], r["condition"], r["team"], r["opp"]): r for r in rows}
    for obj, cond, t in keys:
        mine = [r for r in rows if (r["objective"], r["condition"], r["team"]) == (obj, cond, t)]
        allk = sum(round(r["rate"] * r["n"]) for r in mine)
        alln = sum(r["n"] for r in mine)
        worst = min(mine, key=lambda r: r["rate"])
        base = [by.get((obj, cond, baseline, r["opp"])) for r in mine]
        beats = None
        if t != baseline and all(b is not None for b in base):
            beats = all(r["rate"] > b["rate"] for r, b in zip(mine, base, strict=True))
        head.append({"objective": obj, "condition": cond, "team": t, "overall": wilson(allk, alln),
                     "weakest": {"opp": worst["opp"], "rate": worst["rate"], "lo": worst["lo"], "hi": worst["hi"]},
                     "beats_baseline_everywhere": beats})
    return {"baseline": baseline, "rows": rows, "headline": head}


def markdown(summ: dict[str, Any], n: int) -> str:
    pct = lambda x: f"{100 * x:.0f}%"  # noqa: E731
    lines = ["# Objective success rates\n",
             f"{n} fixed situations per objective, against every opponent; 95% Wilson intervals. "
             "Headline: the rate against the team's weakest opponent. See soccersim/selfplay/objectives.py.\n",
             "| Objective | Condition | Team | Overall | Weakest opponent | Beats "
             f"{summ['baseline']} against every opponent | Target (weakest) | Met |",
             "|---|---|---|---|---|---|---|---|"]
    for h in summ["headline"]:
        p, lo, hi = h["overall"]
        w = h["weakest"]
        b = {True: "yes", False: "no", None: "—"}[h["beats_baseline_everywhere"]]
        tgt = TARGETS.get(h["objective"])
        met = "—" if tgt is None or h["team"] == summ["baseline"] else (
            "yes" if w["rate"] >= tgt and h["beats_baseline_everywhere"] else "no")
        lines.append(f"| {h['objective']} | {h['condition']} | {h['team']} | {pct(p)} ({pct(lo)}–{pct(hi)}) | "
                     f"{pct(w['rate'])} ({pct(w['lo'])}–{pct(w['hi'])}) v {w['opp']} | {b} | "
                     f"{'—' if tgt is None else pct(tgt)} | {met} |")
    lines += ["", "## Every pairing\n", "| Objective | Condition | Team | Opponent | n | Rate (95%) |",
              "|---|---|---|---|---|---|"]
    for r in summ["rows"]:
        lines.append(f"| {r['objective']} | {r['condition']} | {r['team']} | {r['opp']} | {r['n']} | "
                     f"{pct(r['rate'])} ({pct(r['lo'])}–{pct(r['hi'])}) |")
    return "\n".join(lines) + "\n"
