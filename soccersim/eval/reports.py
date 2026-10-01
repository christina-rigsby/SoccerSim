"""Dataset summaries (spec M6): play frequency and success rates by play and opponent,
end reasons, rewards, shots and goals, generator activity."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np

from ..dashboard.xt import fit_xt, placeholder_xt, save_xt
from ..selfplay.logging import load_table

SUCCESS = ("success", "completed")


def summarize(root: str | Path) -> dict[str, Any]:
    d = load_table(root, "decisions", ["episode_id", "team", "chosen", "chosen_source", "end_reason", "reward",
                                       "opponent_id", "generator_used", "library_gap", "phase", "epv_start",
                                       "epv_end", "events"]).to_pylist()
    e = load_table(root, "episodes", ["episode_id", "home", "away", "goals_home", "goals_away", "shots_home",
                                      "shots_away", "end_cause", "duration_s", "xt_shots"]).to_pylist()
    by_play: dict[str, Counter] = defaultdict(Counter)
    rewards: dict[str, list[float]] = defaultdict(list)
    by_opp: dict[tuple[str, str], Counter] = defaultdict(Counter)
    shots_by_source: Counter = Counter()
    for r in d:
        pid = r["chosen"] if r["chosen_source"] == "library" else "<generated>"
        by_play[pid][r["end_reason"]] += 1
        rewards[pid].append(r["reward"])
        by_opp[(pid, r["opponent_id"])]["n"] += 1
        by_opp[(pid, r["opponent_id"])]["ok"] += r["end_reason"] in SUCCESS
        for ev in json.loads(r["events"]):
            if ev["type"] == "shot_taken" and ev["team"] == r["team"]:
                shots_by_source[r["chosen_source"]] += 1
    plays = []
    for pid, c in sorted(by_play.items(), key=lambda kv: -sum(kv[1].values())):
        n = sum(c.values())
        plays.append({"play": pid, "n": n, "share": n / max(len(d), 1),
                      "success_rate": sum(c[k] for k in SUCCESS) / n, "mean_reward": float(np.mean(rewards[pid])),
                      "end_reasons": dict(c)})
    opp = defaultdict(dict)
    for (pid, o), c in by_opp.items():
        opp[pid][o] = {"n": c["n"], "success_rate": c["ok"] / c["n"]}
    goals = sum((x["goals_home"] or 0) + (x["goals_away"] or 0) if x["goals_home"] is not None
                else sum(s[2] for s in json.loads(x["xt_shots"] or "[]")) for x in e)
    shots = sum(x["shots_home"] + x["shots_away"] for x in e)
    return {
        "decisions": len(d), "episodes": len(e), "goals": goals, "shots": shots,
        "sim_seconds": float(sum(x["duration_s"] for x in e)),
        "end_causes": dict(Counter(x["end_cause"] for x in e)),
        "generator_used": sum(r["generator_used"] for r in d), "library_gap": sum(r["library_gap"] for r in d),
        "generated_chosen": sum(r["chosen_source"] != "library" for r in d),
        "shots_by_source": dict(shots_by_source),
        "plays": plays, "success_by_opponent": opp,
    }


def format_summary(s: dict[str, Any]) -> str:
    lines = [f"{s['episodes']} episodes · {s['decisions']} decisions · {s['sim_seconds'] / 60:.0f} sim-minutes · "
             f"{s['shots']} shots · {s['goals']} goals",
             f"library gaps: {s['library_gap']} · generator consulted: {s['generator_used']} · "
             f"generated plays chosen: {s['generated_chosen']}",
             "", f"{'play':34s} {'n':>6s} {'share':>6s} {'success':>8s} {'reward':>8s}"]
    for p in s["plays"]:
        lines.append(f"{p['play']:34s} {p['n']:6d} {p['share']:6.1%} {p['success_rate']:8.1%} {p['mean_reward']:8.4f}")
    return "\n".join(lines)


def fit_xt_from_runs(root: str | Path, out: str | Path) -> dict[str, Any]:
    """Recompute xT from simulator events (spec §11 Phase A) and save it."""
    e = load_table(root, "episodes", ["xt_moves", "xt_shots"]).to_pylist()
    moves = [m for x in e for m in json.loads(x["xt_moves"])]
    shots = [s for x in e for s in json.loads(x["xt_shots"])]
    mv = np.array(moves, dtype=float).reshape(-1, 5)
    sh = np.array(shots, dtype=float).reshape(-1, 3)
    prior = placeholder_xt()
    surf = fit_xt(mv[:, :4], mv[:, 4] > 0, sh[:, :2], sh[:, 2] > 0, prior=prior)
    save_xt(surf, out)
    return {"moves": len(mv), "shots": len(sh), "goals": int(sh[:, 2].sum()) if len(sh) else 0,
            "max": float(surf.values.max()), "path": str(out)}
