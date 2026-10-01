"""Promotion pipeline (spec §11): archive elites that beat the library median in their
niche across all scripted opponents are exported to
``plays/generated_and_promoted/run_<N>/<id>.yaml`` with provenance, flagged for human review.
``N`` numbers league runs: a league directory is given the next free run number the
first time it promotes, and keeps it (re-running ``promote`` rewrites the same folder).
They are not loaded into the library until a person moves them (``load_library`` reads
``offensive/`` and ``defensive/`` only).
"""

from __future__ import annotations

import json
import multiprocessing as mp
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from ..config import PLAYS_DIR, load_config
from ..dashboard.zones import zone_of
from ..schema.validate import parse_play
from .logging import load_table
from .qd_archive import Archive

POSSESSION = ("in_possession", "transition_attack", "set_piece")
PROMOTED_DIR = PLAYS_DIR / "generated_and_promoted"


def run_numbers(root: Path = PROMOTED_DIR) -> list[int]:
    out = []
    for d in root.glob("run_*"):
        if d.is_dir() and d.name[4:].isdigit():
            out.append(int(d.name[4:]))
    return sorted(out)


def promotion_run(league_dir: Path, root: Path = PROMOTED_DIR) -> int:
    """This league's run number: stored in its state.json, assigned on first promotion."""
    path = league_dir / "state.json"
    state = json.loads(path.read_text()) if path.exists() else {}
    if not state.get("promotion_run"):
        state["promotion_run"] = (run_numbers(root) or [0])[-1] + 1
        path.write_text(json.dumps(state, indent=1, default=str))
    return int(state["promotion_run"])


def library_niche_medians(root: str | Path, cache: Path | None = None) -> dict[str, Any]:
    """Median reward of library possession plays per (band, lane) niche and opponent."""
    if cache is not None and cache.exists():
        return json.loads(cache.read_text())
    t = load_table(root, "decisions", ["state", "side", "chosen_source", "phase", "reward", "opponent_id"])
    vals: dict[str, list[float]] = defaultdict(list)
    for r in t.to_pylist():
        if r["chosen_source"] != "library" or r["phase"] not in POSSESSION or not r["state"]:
            continue
        st = json.loads(r["state"])
        if not st:
            continue
        band, lane = zone_of(np.asarray(st["ball"], dtype=float), float(r["side"] or 1.0)).split(".")
        for key in (f"{band}|{lane}|{r['opponent_id']}", f"{band}|{lane}|*", "*"):
            vals[key].append(r["reward"])
    out = {k: float(np.median(v)) for k, v in vals.items() if len(v) >= 5}
    if cache is not None:
        cache.write_text(json.dumps(out))
    return out


def promote_elites(models_dir: str | Path, data_root: str | Path | None = None, out_dir: str | Path | None = None,
                   profile: str | None = None,
                   workers: int = 4, rollouts: int = 4) -> dict[str, Any]:
    from ..generator.train import _eval_generated_job

    league_dir = Path(models_dir) / "league"
    data_root = Path(data_root) if data_root else Path(models_dir).parent / "selfplay"
    run = promotion_run(league_dir, Path(out_dir) if out_dir else PROMOTED_DIR)
    out = (Path(out_dir) if out_dir else PROMOTED_DIR) / f"run_{run}"
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.yaml"):
        old.unlink()  # re-promoting the same run replaces its folder
    tcfg = load_config("training")
    archive = Archive.load(league_dir / "archive.json", tcfg["qd"][f"min_evals_{profile or tcfg['profile']}"])
    styles = list(load_config("league")["scripted_styles"])
    medians = library_niche_medians(data_root, league_dir / "library_niche.json")
    meta = json.loads((Path(models_dir) / "meta.json").read_text()) if (Path(models_dir) / "meta.json").exists() \
        else {}
    state = json.loads((league_dir / "state.json").read_text()) if (league_dir / "state.json").exists() else {}

    cells = archive.cells()
    elites = [(k, c) for k, c in cells.items() if c["elite"]]
    # Make sure every elite has evaluations against every scripted style (held-out one included).
    jobs = []
    for _, c in elites:
        e = archive.plays[c["elite"]]
        have = {ev[1] for ev in e["evals"]}
        for s in styles:
            if s not in have:
                jobs.append({"play": e["play"], "band": e["desc"][0], "opponent": s,
                             "seeds": list(range(500, 500 + rollouts * 3)), "rollouts": rollouts})
    if jobs:
        with mp.get_context("fork").Pool(workers) as pool:
            for job, r in zip(jobs, pool.map(_eval_generated_job, jobs), strict=True):
                e = archive.plays[r["id"]]
                for rw in r["rewards"]:
                    archive.add(e["play"], e["desc"], rw, job["opponent"], source="promotion")
        archive.save(league_dir / "archive.json")

    report = []
    for key, c in elites:
        e = archive.plays[c["elite"]]
        band, lane = e["desc"][0], e["desc"][1]
        per_opp = {}
        beats = True
        for s in styles:
            r = [ev[0] for ev in e["evals"] if ev[1] == s]
            mean = float(np.mean(r)) if r else None
            med = medians.get(f"{band}|{lane}|{s}", medians.get(f"{band}|{lane}|*", medians.get("*", 0.0)))
            ok = mean is not None and mean >= med
            beats &= ok
            per_opp[s] = {"mean_reward": mean, "n": len(r), "library_median": med, "beats": ok}
        entry = {"id": c["elite"], "cell": key, "promoted": beats, "per_opponent": per_opp,
                 "overall": archive.stats(c["elite"])}
        if beats:
            play = dict(e["play"], source="promoted")
            play["provenance"] = {
                "status": "pending_human_review",
                "archive_cell": dict(zip(("band", "lane", "tempo", "passes", "objective"), e["desc"], strict=True)),
                "metrics": {"overall": archive.stats(c["elite"]), "per_opponent": per_opp},
                "generating_checkpoint": str(league_dir / "main.pt"), "league_update": state.get("update"),
                "training_profile": meta.get("profile"), "run": run,
            }
            parse_play(play)  # promoted plays pass the same validator
            path = out / f"{c['elite']}.yaml"
            path.write_text("# Generated by Module 3 and promoted from the QD archive. PENDING HUMAN REVIEW:\n"
                            "# move into plays/offensive/ only after a person has checked it.\n"
                            + yaml.safe_dump(play, sort_keys=False, width=110))
            entry["path"] = str(path)
        report.append(entry)
    summary = {"run": run, "dir": str(out), "elites": len(elites), "promoted": sum(r["promoted"] for r in report),
               "candidates": report}
    (league_dir / "promotion.json").write_text(json.dumps(summary, indent=2))
    return {k: v for k, v in summary.items() if k != "candidates"} | {
        "promoted_ids": [r["id"] for r in report if r["promoted"]]}
