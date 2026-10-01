"""One self-play episode, runnable in a worker process (spec §11; simulator single-threaded)."""

from __future__ import annotations

from typing import Any

import numpy as np

from ..schema import load_library
from ..sim.env import MatchEnv
from ..sim.scenarios import Scenario
from .logging import episode_rows
from .policies import make_policy

_CACHE: dict[str, Any] = {}


def _library():
    if "lib" not in _CACHE:
        _CACHE["lib"] = load_library()
    return _CACHE["lib"]


def run_job(job: dict[str, Any]) -> dict[str, Any]:
    """Run one episode described by ``job`` and return its log rows.

    ``job`` keys: episode_id, seed, scenario (dict), home, away (policy specs), randomise,
    max_time_s, save_tracking, sim_overrides (optional dict merged into the sim config).
    """
    lib = _library()
    seed = int(job["seed"])
    env = MatchEnv(randomise=job.get("randomise", True), record_frames=True)
    if job.get("sim_cfg") is not None:
        env.base_cfg = job["sim_cfg"]
    sc = job["scenario"]
    scenario = Scenario(**{k: v for k, v in sc.items() if k != "score"}, score=tuple(sc.get("score", (0, 0))))
    env.reset(seed, scenario)
    rng = np.random.default_rng(seed + 7919)
    home = make_policy(job["home"], lib, np.random.default_rng(rng.integers(1 << 31)))
    away = make_policy(job["away"], lib, np.random.default_rng(rng.integers(1 << 31)))
    res = env.run(home, away, max_time_s=job.get("max_time_s"))
    for pol in (home, away):
        bundle = getattr(pol, "bundle", None)
        if bundle is not None:
            for rec in res.plays:
                if rec["source"] != "library" and rec["play_id"] in bundle.gen_tokens:
                    rec["tokens"] = bundle.gen_tokens[rec["play_id"]]
    rows, ep = episode_rows(res, job["episode_id"], lib, job["home"]["id"], job["away"]["id"],
                            job.get("checkpoint", ""))
    out = {"rows": rows, "episode": ep, "score": res.score, "duration": res.duration_s}
    if job.get("save_tracking"):
        from ..viz.replay_html import episode_payload

        out["tracking"] = episode_payload(res, job.get("title", job["episode_id"]))
    # Learning agents hand back their chosen generated plays with realised rewards (PPO).
    for pol, team in ((home, 0), (away, 1)):
        if hasattr(pol, "finalize"):
            out.setdefault("rollouts", {})[team] = pol.finalize(res.plays)
            gen = getattr(pol, "generator", None)
            if gen is not None:
                out.setdefault("gen_stats", {})[team] = dict(gen.stats)
    out["plays"] = [{k: p.get(k) for k in ("play_id", "source", "team", "reward", "end_reason", "t_start",
                                           "steps_visited", "play_yaml", "state", "side")} for p in res.plays]
    out["events"] = [e for e in res.events if e["type"] in ("shot_taken", "goal")]
    return out
