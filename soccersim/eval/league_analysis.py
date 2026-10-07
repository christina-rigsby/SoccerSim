"""Analyses of a league run from its logs: every reward, not just means.

- :func:`reward_distributions`: every reward of the plays each learner called, per league
  update, split into generated and library plays.
- :func:`zone_opponent_table`: for the main agent, per start zone x opponent, how often it was
  deciding there, how often it called a generated play, and the rewards.
- :func:`phase_a_payoff`: who beat whom in the Phase A self-play games (the library team and
  the training styles all play each other there).

Rewards are per play, in EPV units (see :mod:`soccersim.selfplay.rewards`). The "score" of a
game uses the league's rule: goals decide; with no goals, the team with more total reward wins
unless the difference is under 0.005 (a draw).
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

from ..dashboard.zones import zone_of
from ..selfplay.logging import load_table

POSSESSION = ("in_possession", "transition_attack")
LEARNERS = ("main", "main_exploiter", "league_exploiter")
DRAW_BAND = 0.005


def _league_runs(root: Path) -> list[tuple[int, Path]]:
    out = []
    for d in Path(root).glob("run=league_u*"):
        m = re.match(r"run=league_u(\d+)$", d.name)
        if m:
            out.append((int(m.group(1)) + 1, d))  # logs of update index u are update u + 1
    return sorted(out)


def _rows(run_dir: Path, cols: list[str]) -> tuple[list[dict], dict[str, dict]]:
    rows = load_table(run_dir, "decisions", cols).to_pylist()
    eps = {e["episode_id"]: e for e in load_table(run_dir, "episodes", ["episode_id", "home", "away"]).to_pylist()}
    return rows, eps


def reward_distributions(root: str | Path) -> list[dict[str, Any]]:
    """Per update and learner, every reward of the possession plays it called."""
    out = []
    for update, d in _league_runs(Path(root)):
        rows, eps = _rows(d, ["episode_id", "team", "phase", "chosen", "chosen_source", "reward"])
        rec: dict[str, dict[str, list[float]]] = {n: {"generated": [], "library": []} for n in LEARNERS}
        for r in rows:
            if r["phase"] not in POSSESSION or r["chosen"] is None or r["reward"] is None:
                continue
            ep = eps.get(r["episode_id"])
            if ep is None:
                continue
            who = ep["home"] if r["team"] == 0 else ep["away"]
            if who in rec:
                rec[who]["library" if r["chosen_source"] == "library" else "generated"].append(round(r["reward"], 5))
        out.append({"update": update, **rec})
    return out


def zone_opponent_table(root: str | Path, who: str = "main") -> dict[str, Any]:
    """Start zone x opponent for ``who``'s possession decisions over the whole league run."""
    cells: dict[tuple[str, str], dict[str, list[float]]] = defaultdict(lambda: {"generated": [], "library": []})
    for _, d in _league_runs(Path(root)):
        rows, eps = _rows(d, ["episode_id", "team", "phase", "chosen", "chosen_source", "reward", "state", "side"])
        for r in rows:
            if r["phase"] not in POSSESSION or r["chosen"] is None or r["reward"] is None or not r["state"]:
                continue
            ep = eps.get(r["episode_id"])
            if ep is None or (ep["home"] if r["team"] == 0 else ep["away"]) != who:
                continue
            opp = ep["away"] if r["team"] == 0 else ep["home"]
            st = json.loads(r["state"])
            if not st:
                continue
            band, lane = zone_of(np.asarray(st["ball"], dtype=float), float(r["side"] or 1.0)).split(".")
            kind = "library" if r["chosen_source"] == "library" else "generated"
            cells[(f"{band}.{lane}", opp)][kind].append(r["reward"])
    table = []
    for (zone, opp), c in sorted(cells.items()):
        allr = c["generated"] + c["library"]
        table.append({"zone": zone, "opponent": opp, "n": len(allr), "mean_reward": float(np.mean(allr)),
                      "generated_n": len(c["generated"]),
                      "generated_mean": float(np.mean(c["generated"])) if c["generated"] else None,
                      "library_mean": float(np.mean(c["library"])) if c["library"] else None})
    # Do zones with higher reward come up more often? Rank correlation per opponent.
    corr = {}
    for opp in sorted({t["opponent"] for t in table}):
        rows = [t for t in table if t["opponent"] == opp and t["n"] >= 5]
        if len(rows) >= 4:
            corr[opp] = _spearman([t["mean_reward"] for t in rows], [t["n"] for t in rows])
    return {"who": who, "cells": table, "reward_frequency_spearman": corr}


def _spearman(a: list[float], b: list[float]) -> float:
    ra = np.argsort(np.argsort(a)).astype(float)
    rb = np.argsort(np.argsort(b)).astype(float)
    if ra.std() == 0 or rb.std() == 0:
        return 0.0
    return float(np.corrcoef(ra, rb)[0, 1])


def phase_a_payoff(root: str | Path, run_id: str = "phase_a") -> dict[str, Any]:
    """Payoff between the Phase A teams (library team and training styles), from the logs."""
    from ..eval.elo import Payoff

    d = Path(root) / f"run={run_id}"
    eps = load_table(d, "episodes", ["episode_id", "home", "away", "goals_home", "goals_away"]).to_pylist()
    rew: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for r in load_table(d, "decisions", ["episode_id", "team", "reward"]).to_pylist():
        if r["reward"] is not None:
            rew[r["episode_id"]][r["team"]] += r["reward"]
    pay = Payoff()
    for e in eps:
        r0, r1 = rew.get(e["episode_id"], (0.0, 0.0))
        gd = (e["goals_home"] or 0) - (e["goals_away"] or 0)
        score = 1.0 if gd > 0 else 0.0 if gd < 0 else (0.5 if abs(r0 - r1) < DRAW_BAND else float(r0 > r1))
        pay.add(e["home"], e["away"], score, r0 - r1)
    return pay.to_json()


def summarize_distribution(values: list[float]) -> dict[str, Any]:
    v = np.asarray(values, dtype=float)
    if not len(v):
        return {"n": 0}
    q = np.percentile(v, [5, 25, 50, 75, 95])
    return {"n": int(len(v)), "mean": float(v.mean()), "p5": float(q[0]), "q1": float(q[1]), "median": float(q[2]),
            "q3": float(q[3]), "p95": float(q[4]), "share_positive": float((v > DRAW_BAND).mean()),
            "share_negative": float((v < -DRAW_BAND).mean())}
