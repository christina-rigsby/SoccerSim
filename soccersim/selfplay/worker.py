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
    if job.get("save_generated_successes"):
        out["success_clips"] = generated_success_clips(res, job)
    out["plays"] = [{k: p.get(k) for k in ("play_id", "source", "team", "reward", "end_reason", "t_start",
                                           "steps_visited", "play_yaml", "state", "side")} for p in res.plays]
    out["events"] = [e for e in res.events if e["type"] in ("shot_taken", "goal")]
    return out


#: A generated play counts as successful when it reached its own success condition, or when it
#: raised expected possession value by at least this much (EPV units).
SUCCESS_MIN_REWARD = 0.005


def generated_success_clips(res, job: dict[str, Any], before: float = 1.0, after: float = 2.0) -> list[dict[str, Any]]:
    """Replay clips (with the play's definition) of every generated play in ``res`` that succeeded."""
    from ..viz.replay_html import episode_payload

    clips = []
    ids = (job["home"]["id"], job["away"]["id"])
    for rec in res.plays:
        if rec["source"] == "library" or not rec.get("play_yaml"):
            continue
        reward = rec.get("reward")
        why = [w for w, ok in (("reached its success condition", rec["end_reason"] == "success"),
                               (f"gained at least {SUCCESS_MIN_REWARD} EPV",
                                reward is not None and reward >= SUCCESS_MIN_REWARD)) if ok]
        if not why:
            continue
        lo, hi = rec["t_start"] - before, rec["t_end"] + after
        counter = sorted({p["play_id"] for p in res.plays
                          if p["team"] != rec["team"] and p["t_start"] < rec["t_end"] and p["t_end"] > rec["t_start"]})
        ep = episode_payload(res, "")
        ep["frames"] = [f for f in ep["frames"] if lo <= f["t"] <= hi]
        ep["plays"] = [q for q in ep["plays"] if q["t_start"] < hi and q["t_end"] > lo]
        ep["decisions"] = [d for d in ep["decisions"] if lo <= d["t"] <= hi]
        ep["events"] = [e for e in ep["events"] if lo <= e["t"] <= hi]
        clips.append({
            "episode_id": job["episode_id"], "play_id": rec["play_id"], "team": rec["team"],
            "player": ids[rec["team"]], "opponent": ids[1 - rec["team"]], "counter_plays": counter,
            "reward": reward, "end_reason": rec["end_reason"], "why": why, "steps": rec.get("steps_visited"),
            "t_start": rec["t_start"], "t_end": rec["t_end"], "play_yaml": rec["play_yaml"], "replay": ep,
        })
    return clips
