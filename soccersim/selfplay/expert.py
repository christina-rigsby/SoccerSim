"""Expert iteration: objective-driven search distilled into a fast network (step 4 of the plan).

The objective-driven look-ahead team (soccersim/ranking/lookahead.py with ``objective``) decides
well but slowly: it plays every candidate forward several times before each call. Expert
iteration makes that knowledge fast and lets it improve:

1. **Search** (iteration ``i``): the look-ahead team plays the objective's situations
   (soccersim/selfplay/objectives.py) against the training styles and the plain library, never
   the held-out styles, and every decision is saved with the situation, the players' capabilities
   *at that moment* (fatigue, substitutions), and each candidate's trial values for the objective
   (``data/expert_pool_v<N>/<objective>/iter_<i>/``).
2. **Distil**: a network (the critic architecture) learns to predict, from the situation alone,
   how each candidate compares with the others in that decision (``data/models/expert/<objective>/
   iter_<i>/critic.pt``). Team ``expert@<objective>`` (latest iteration) or
   ``expert<i>@<objective>`` calls the play the network rates highest, with no simulation.
3. **Iterate**: the next search is built on the network (``base``): the network proposes the
   candidates and plays on in the trials, so the search starts from a better policy and its
   choices, distilled again, improve the network further.

Training situations use seeds different from the evaluation's, so the objective evaluation
measures situations the network has never seen.

    python scripts/expert.py --objective keep_30 --games 400 --iterations 2
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..config import load_config
from .objectives import OBJECTIVES, situations

TRAIN_SEED = 1_000_003  # situations for training; the evaluation uses seed 7


def data_path(objective: str, it: int, root: str | Path = "data") -> Path:
    v = load_config("league").get("pool_version", 1)
    return Path(root) / f"expert_pool_v{v}" / objective / f"iter_{it}"


def model_path(objective: str, it: int, models_dir: str | Path = "data/models") -> Path:
    return Path(models_dir) / "expert" / objective / f"iter_{it}"


def latest_iteration(objective: str, models_dir: str | Path = "data/models") -> int | None:
    its = [int(p.name.split("_")[1]) for p in (Path(models_dir) / "expert" / objective).glob("iter_*")
           if (p / "critic.pt").exists()]
    return max(its) if its else None


def expert_spec(objective: str, it: int | None = None, models_dir: str | Path = "data/models",
                name: str | None = None) -> dict[str, Any]:
    """The distilled network of ``objective`` (iteration ``it``; default the latest) as a team."""
    it = latest_iteration(objective, models_dir) if it is None else it
    if it is None:
        raise ValueError(f"no expert network for {objective!r} in {models_dir}/expert")
    return {"id": name or f"expert{it}@{objective}", "kind": "agent",
            "checkpoint": str(model_path(objective, it, models_dir)), "generator": False, "critic": True,
            "score_mode": "learned", "temperature": 0.0}


def search_spec(objective: str, it: int, models_dir: str | Path = "data/models") -> dict[str, Any]:
    """The search of iteration ``it``: the fast objective-driven look-ahead, built on the best selector
    for iteration 0 and on the previous iteration's network after that."""
    from .evaluate import team_spec

    spec = {**team_spec(f"lookahead_fast@{objective}", models_dir), "record_state": True,
            "id": f"search{it}@{objective}"}
    if it > 0:
        spec["base"] = expert_spec(objective, it - 1, models_dir)
    return spec


def search_jobs(objective: str, n_games: int, it: int, models_dir: str | Path = "data/models") -> list[dict]:
    from .evaluate import team_spec

    lcfg = load_config("league")
    opps = [s for s in lcfg["scripted_styles"] if s not in lcfg["held_out_styles"]] + ["library"]
    spec = OBJECTIVES[objective]
    me = search_spec(objective, it, models_dir)
    jobs = []
    for k, s in enumerate(situations(objective, n_games, TRAIN_SEED + it)):
        side = s["our_side"]
        forms = (s["our_formation"], s["their_formation"]) if side == 0 else (s["their_formation"],
                                                                           s["our_formation"])
        ours, theirs = spec.get("score", (0, 0))
        jobs.append({"game_id": f"X{it}-{k:05d}", "seed": s["seed"], "side": side,
                     "scenario": {"type": s["type"], "attacking_team": side if spec["ours"] else 1 - side,
                                  "home_formation": forms[0], "away_formation": forms[1], "minute": s["minute"],
                                  "score": [ours, theirs] if side == 0 else [theirs, ours]},
                     "me": me, "opp": team_spec(opps[k % len(opps)], models_dir),
                     "max_time_s": spec["seconds"], "stop_on_goal": True})
    return jobs


def run(objective: str, n_games: int, iterations: int, workers: int = 4, models_dir: str | Path = "data/models",
        root: str | Path = "data", epochs: int = 12) -> list[dict[str, Any]]:
    """Search, distil, repeat (each finished iteration is kept and skipped on a rerun)."""
    import json

    from .trial_critic import train, write_chunks

    out = []
    for it in range(iterations):
        mp = model_path(objective, it, models_dir)
        if (mp / "critic.pt").exists():
            out.append(json.loads((mp / "metrics.json").read_text()))
            print(f"== {objective} iteration {it}: already trained", flush=True)
            continue
        print(f"== {objective} iteration {it}: search", flush=True)
        write_chunks(search_jobs(objective, n_games, it, models_dir), data_path(objective, it, root), workers)
        print(f"== {objective} iteration {it}: distil", flush=True)
        res = train(models_dir, root, epochs=epochs, data_path=data_path(objective, it, root), out_path=mp)
        res["objective"], res["iteration"] = objective, it
        (mp / "metrics.json").write_text(json.dumps(res, indent=1))
        out.append(res)
    return out
