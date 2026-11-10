"""The library-only learned play selector: the second model, next to the generator agent.

It never writes plays. It learns *which library play to call*: a value model (the critic's
architecture) predicts each feasible play's learning target (``rewards.target``, by default
the possession return) in the current situation, and the play with the highest prediction is
called; the hand-written score is not used (``score_mode: learned``).

Training is iterative, so it learns from the consequences of its own choices:

1. fit the value model on the Phase A library self-play data;
2. play a batch of games against the training styles and the plain library team, calling a
   random feasible play with probability ``epsilon`` (so it also sees what the plays it would
   not choose lead to);
3. refit on Phase A plus all its own games, lower ``epsilon``, repeat.

Everything lives in ``data/models/selector/``; its games are logged under the self-play root as
``run=selector_i<k>``. The validation round-robin includes it as the team ``selector``.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import numpy as np

from ..config import load_config
from ..sim.scenarios import SCENARIO_TYPES, sample_scenario
from .policies import style_spec
from .runner import run_jobs

SELECTOR_DIR = "selector"


def selector_dir(models_dir: str | Path) -> Path:
    return Path(models_dir) / SELECTOR_DIR


def selector_spec(models_dir: str | Path, epsilon: float = 0.0, pid: str = "selector") -> dict[str, Any]:
    return {"id": pid, "kind": "agent", "checkpoint": str(selector_dir(models_dir)), "generator": False,
            "critic": True, "score_mode": "learned", "epsilon": float(epsilon), "temperature": 0.0}


def _training_roots(data_root: Path) -> list[Path]:
    """Library self-play runs (Phase A; not league or validation games) plus the selector's own."""
    runs = sorted(d for d in data_root.glob("run=*") if d.is_dir())
    library = [d for d in runs if not d.name.startswith(("run=league_", "run=selector_", "run=heldout"))]
    return library + [d for d in runs if d.name.startswith("run=selector_")]


def _fit(models_dir: Path, data_root: Path, profile: str | None, max_rows: int | None) -> dict[str, Any]:
    from ..generator.train import train_critic_and_response

    out = selector_dir(models_dir)
    out.mkdir(parents=True, exist_ok=True)
    res = train_critic_and_response(_training_roots(data_root), out, profile=profile, max_rows=max_rows,
                                    keep_prefix=("S",))
    return {"rows": res["rows"], "mse": res["critic"]["mse"], "baseline_mse": res["critic"]["baseline_mse"],
            "mean_mse": res["critic"]["mean_mse"]}


def train_selector(models_dir: str | Path, data_root: str | Path, iterations: int | None = None,
                   games: int | None = None, workers: int = 4, profile: str | None = None,
                   seed: int = 0) -> dict[str, Any]:
    """Run (or resume) the selector's training iterations; returns its history."""
    models_dir, data_root = Path(models_dir), Path(data_root)
    cfg = load_config("training").get("selector", {})
    iterations = iterations or int(cfg.get("iterations", 4))
    games = games or int(cfg.get("games_per_iteration", 300))
    eps0, eps1 = float(cfg.get("epsilon_start", 0.2)), float(cfg.get("epsilon_end", 0.05))
    max_rows = cfg.get("max_rows")
    lcfg = load_config("league")
    opponents = [s for s in lcfg["scripted_styles"] if s not in lcfg["held_out_styles"]] + ["library"]
    d = selector_dir(models_dir)
    state_path = d / "state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {"history": []}

    if not state.get("fitted_on_phase_a"):
        t0 = time.time()
        fit = _fit(models_dir, data_root, profile, max_rows)
        state.update(fitted_on_phase_a=True)
        state["history"].append({"iteration": 0, "fit": fit, "wall_s": round(time.time() - t0, 1)})
        state_path.write_text(json.dumps(state, indent=1))
        print(f"  selector iteration 0: value model fitted on Phase A ({fit['rows']} rows), held-out MSE "
              f"{fit['mse']:.6f} vs per-play {fit['baseline_mse']:.6f}", flush=True)

    done = max(h["iteration"] for h in state["history"])
    for it in range(done + 1, iterations + 1):
        t0 = time.time()
        eps = eps0 + (eps1 - eps0) * (it - 1) / max(iterations - 1, 1)
        rng = np.random.default_rng(seed + it)
        jobs = []
        for k in range(games):
            sc = sample_scenario(rng, SCENARIO_TYPES[:-2] + ("random_open_play",), tuple(lcfg["formations"]))
            opp = opponents[k % len(opponents)]
            other = {"id": "library", "kind": "library", "temperature": 0.01} if opp == "library" else \
                style_spec(opp, lcfg)
            me = selector_spec(models_dir, eps)
            home, away = (me, other) if k % 2 == 0 else (other, me)
            jobs.append({"episode_id": f"S{it:02d}-{k:05d}", "seed": int(rng.integers(1 << 31)),
                         "scenario": sc.to_dict(), "home": home, "away": away, "randomise": True})
        res: list[dict] = []
        run_jobs(jobs, data_root, f"selector_i{it:02d}", workers=workers, on_result=res.append, progress_every=0)
        rew, shots, goals_for, goals_against = [], 0, 0, 0
        for x in res:
            ep = x["episode"]
            team = 0 if ep["home"] == "selector" else 1
            rew += [r["reward"] for r in x["rows"] if r["team"] == team]
            shots += ep["shots_home"] if team == 0 else ep["shots_away"]
            goals_for += ep["goals_home"] if team == 0 else ep["goals_away"]
            goals_against += ep["goals_away"] if team == 0 else ep["goals_home"]
        fit = _fit(models_dir, data_root, profile, max_rows)
        rec = {"iteration": it, "epsilon": round(eps, 3), "games": len(res),
               "mean_play_reward": float(np.mean(rew)) if rew else 0.0, "shots": int(shots),
               "goals_for": int(goals_for), "goals_against": int(goals_against), "fit": fit,
               "wall_s": round(time.time() - t0, 1)}
        state["history"].append(rec)
        state_path.write_text(json.dumps(state, indent=1))
        print(f"  selector iteration {it}: {len(res)} games (epsilon {eps:.2f}), mean play reward "
              f"{rec['mean_play_reward']:+.4f}, goals {goals_for}-{goals_against}, shots {shots}; refit MSE "
              f"{fit['mse']:.6f} vs per-play {fit['baseline_mse']:.6f}", flush=True)
    return state
