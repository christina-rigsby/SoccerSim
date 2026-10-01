"""Multiprocess self-play runner (spec §11 Phase A, M6).

Workers each run whole episodes single-threaded; the parent writes Parquet. Use
:func:`phase_a_jobs` for library self-play across scenarios, formations and randomised
capabilities, with exploration temperature tau > 0 on both sides.
"""

from __future__ import annotations

import multiprocessing as mp
import time
import uuid
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import numpy as np

from ..config import load_config
from ..sim.scenarios import SCENARIO_TYPES, sample_scenario
from .logging import ParquetLog
from .worker import run_job


def phase_a_jobs(n: int, seed: int = 0, temperature: float = 0.01, include_styles: bool = True,
                 tracking_every: int = 0, run_id: str = "a") -> list[dict[str, Any]]:
    league = load_config("league")
    rng = np.random.default_rng(seed)
    styles = list(league["scripted_styles"]) if include_styles else []
    jobs = []
    for i in range(n):
        sc = sample_scenario(rng, SCENARIO_TYPES[:-2] + ("random_open_play",), tuple(league["formations"]))
        specs = [{"id": "library", "kind": "library", "temperature": temperature}]
        if styles:
            specs += [{"id": s, "kind": "style", "style": s, "temperature": temperature} for s in styles]
        home = specs[int(rng.integers(len(specs)))]
        away = specs[int(rng.integers(len(specs)))]
        jobs.append({
            "episode_id": f"{run_id}-{i:06d}", "seed": int(rng.integers(1 << 31)), "scenario": sc.to_dict(),
            "home": home, "away": away, "randomise": True,
            "save_tracking": bool(tracking_every and i % tracking_every == 0),
        })
    return jobs


def run_jobs(jobs: Iterable[dict[str, Any]], out_root: str | Path | None = None, run_id: str | None = None,
             workers: int = 0, on_result: Callable[[dict], None] | None = None,
             progress_every: int = 200) -> dict[str, Any]:
    """Run jobs (in a process pool when ``workers > 1``) and log to Parquet under ``out_root``."""
    jobs = list(jobs)
    run_id = run_id or uuid.uuid4().hex[:8]
    log = ParquetLog(out_root, run_id) if out_root else None
    n_rows = 0
    t0 = time.time()
    results_iter: Iterable[dict]
    pool = None
    if workers and workers > 1:
        ctx = mp.get_context("fork")
        pool = ctx.Pool(workers)
        results_iter = pool.imap_unordered(run_job, jobs, chunksize=4)
    else:
        results_iter = map(run_job, jobs)
    sim_s = 0.0
    try:
        for k, res in enumerate(results_iter, 1):
            n_rows += len(res["rows"])
            sim_s += res["duration"]
            if log:
                log.add(res["rows"], res["episode"])
                if "tracking" in res:
                    log.save_tracking(res["episode"]["episode_id"], res["tracking"])
            if on_result:
                on_result(res)
            if progress_every and k % progress_every == 0:
                el = time.time() - t0
                print(f"  {k}/{len(jobs)} episodes, {n_rows} decisions, {el:.0f}s wall, "
                      f"{sim_s / max(el, 1e-9):.0f}x real time", flush=True)
    finally:
        if pool:
            pool.close()
            pool.join()
        if log:
            log.flush()
    return {"run_id": run_id, "episodes": len(jobs), "decisions": n_rows, "wall_s": time.time() - t0,
            "dir": str(log.dir) if log else None}
