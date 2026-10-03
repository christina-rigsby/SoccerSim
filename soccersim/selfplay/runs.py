"""Run lineage: how one league run builds on the ones before it (D-044).

A *run* is one league training run. Its directory is ``data/models/runs/run_<N>/`` and its
promoted plays go to ``plays/generated_and_promoted/run_<N>/``. Each run carries forward:

1. **Prior promoted plays are mutated** — they join the library plays as mutation parents in
   generator pretraining (:func:`soccersim.generator.train.mutation_filter`).
2. **Prior promoted plays are imitated** — they are behaviour-cloning targets in the states
   where they were replayed.
3. **Prior promoted plays seed the archive** — a new play must beat them in their niche.
4. **The generator continues** from the previous run, but only under guardrails:
   the opponent pool must be identical (:func:`pool_fingerprint`), and the previous run must
   have passed its regression gate; otherwise the run starts from a last-good generator.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ..config import PLAYS_DIR
from ..schema.models import Play
from ..schema.validate import PlayValidationError, parse_play

PROMOTED_DIR = PLAYS_DIR / "generated_and_promoted"
LEARNERS = ("main", "main_exploiter", "league_exploiter")


def runs_root(models_dir: str | Path) -> Path:
    return Path(models_dir) / "runs"


def run_dirs(models_dir: str | Path) -> dict[int, Path]:
    """Existing run directories by run number."""
    out = {}
    for d in runs_root(models_dir).glob("run_*"):
        if d.is_dir() and d.name[4:].isdigit() and (d / "state.json").exists():
            out[int(d.name[4:])] = d
    return dict(sorted(out.items()))


def promoted_run_numbers(root: Path = PROMOTED_DIR) -> list[int]:
    return sorted(int(d.name[4:]) for d in root.glob("run_*") if d.is_dir() and d.name[4:].isdigit())


def next_run_number(models_dir: str | Path, promoted_root: Path = PROMOTED_DIR) -> int:
    used = list(run_dirs(models_dir)) + promoted_run_numbers(promoted_root)
    return (max(used) if used else 0) + 1


def latest_run_dir(models_dir: str | Path) -> Path | None:
    dirs = run_dirs(models_dir)
    return dirs[max(dirs)] if dirs else None


def read_state(run_dir: Path) -> dict[str, Any]:
    p = run_dir / "state.json"
    return json.loads(p.read_text()) if p.exists() else {}


# -- opponent pool consistency ---------------------------------------------------------------


def pool_definition(league_cfg: dict) -> dict[str, Any]:
    """What a run trains against. Two runs may share a generator only if this is identical.

    Keys absent from an older config are left out rather than defaulted, so a pool recorded
    before they existed still compares equal to itself.
    """
    out = {
        "scripted_styles": league_cfg["scripted_styles"],
        "held_out_styles": sorted(league_cfg["held_out_styles"]),
        "pfsp_weighting": league_cfg["pfsp_weighting"],
        "learners": list(LEARNERS),
        "snapshot_every": league_cfg["snapshot_every"],
        "main_exploiter_reset_every": league_cfg["main_exploiter_reset_every"],
    }
    for k in ("pool_version", "formations", "randomise_eval_formations"):
        if k in league_cfg:
            out[k] = league_cfg[k]
    if league_cfg.get("pool_version", 1) >= 2:
        # Scripted styles choose from the library, so its exact content is part of the pool.
        out["library"] = library_fingerprint()
    return out


def library_fingerprint(library: dict[str, Play] | None = None) -> str:
    from ..schema import load_library
    from ..schema.loader import play_to_dict

    lib = library if library is not None else load_library()
    blob = json.dumps({pid: play_to_dict(p) for pid, p in sorted(lib.items())}, sort_keys=True, default=str)
    return hashlib.sha1(blob.encode()).hexdigest()[:12]


def pool_fingerprint(league_cfg: dict) -> str:
    blob = json.dumps(pool_definition(league_cfg), sort_keys=True).encode()
    return hashlib.sha1(blob).hexdigest()[:12]


def pool_label(league_cfg: dict) -> str:
    return f"v{league_cfg.get('pool_version', 1)} ({pool_fingerprint(league_cfg)})"


def data_paths(league_cfg: dict | None = None) -> dict[str, Path]:
    """This pool's self-play data root and held-out reference root (repo-relative in config)."""
    from ..config import REPO_ROOT, load_config

    cfg = (league_cfg or load_config("league")).get("data") or {}
    sp = REPO_ROOT / cfg.get("selfplay", "data/selfplay")
    ref = cfg.get("heldout_reference")
    return {"selfplay": sp, "heldout_reference": REPO_ROOT / ref if ref else None}


def check_base_models(models_dir: str | Path, league_cfg: dict) -> None:
    """Refuse to start a run on a critic / generator trained for a different opponent pool.

    ``meta.json`` records the pool fingerprint when they were trained; models from before
    that was recorded are accepted (they can only belong to pool v1).
    """
    meta_path = Path(models_dir) / "meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    cur = pool_fingerprint(league_cfg)
    for what in ("critic", "generator"):
        fp = meta.get(f"{what}_pool_fingerprint")
        if fp is None:
            if league_cfg.get("pool_version", 1) > 1:
                raise RuntimeError(f"the {what} in {models_dir} predates pool versioning; retrain it for pool "
                                   f"{pool_label(league_cfg)} (train-critic / pretrain-generator) first")
            continue
        if fp != cur:
            raise RuntimeError(f"the {what} in {models_dir} was trained for opponent pool {fp}, not the current "
                               f"pool {pool_label(league_cfg)}; regenerate Phase A data and retrain first")


def pool_differences(a: dict[str, Any], b: dict[str, Any]) -> list[str]:
    return sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))


# -- prior promoted plays ----------------------------------------------------------------------


def prior_promoted(before_run: int | None = None, root: Path = PROMOTED_DIR) -> list[Play]:
    """Promoted plays from every run folder numbered below ``before_run`` (all if ``None``)."""
    out = []
    for n in promoted_run_numbers(root):
        if before_run is not None and n >= before_run:
            continue
        for f in sorted((root / f"run_{n}").glob("*.yaml")):
            import yaml

            data = yaml.safe_load(f.read_text())
            data.setdefault("provenance", {})["run"] = n
            try:
                out.append(parse_play(data))
            except PlayValidationError:
                continue  # a hand-edited file that no longer validates is skipped, never repaired
    return out


# -- where a new run starts --------------------------------------------------------------------


def plan_start(models_dir: str | Path, league_cfg: dict, mode: str = "auto") -> dict[str, Any]:
    """Decide which generator a new run starts from.

    ``mode``: ``auto`` (guardrails), ``fresh`` (always the pretrained generator), or
    ``force`` (continue from the previous run's final generator whatever the checks say).
    """
    phase_b = Path(models_dir) / "generator.pt"
    fresh = {"start_from": str(phase_b), "continued_from": None}
    prev_dir = latest_run_dir(models_dir)
    if mode == "fresh":
        return {**fresh, "reason": "fresh start requested"}
    if prev_dir is None:
        return {**fresh, "reason": "first run"}
    prev = read_state(prev_dir)
    prev_n = prev.get("run")
    if mode == "force":
        return {"start_from": str(prev_dir / "main.pt"), "continued_from": prev_n,
                "reason": f"forced continuation from run {prev_n}"}
    cur_pool = pool_definition(league_cfg)
    prev_pool = prev.get("pool")
    if prev_pool is None:
        return {**fresh, "reason": f"run {prev_n} has no recorded opponent pool"}
    if prev_pool != cur_pool:
        diff = ", ".join(pool_differences(prev_pool, cur_pool))
        return {**fresh, "reason": f"opponent pool changed since run {prev_n} ({diff}); not continuing"}
    gate = prev.get("gate") or {}
    if gate.get("passed") is True:
        return {"start_from": str(prev_dir / "main.pt"), "continued_from": prev_n,
                "reason": f"run {prev_n} passed its regression gate"}
    if gate.get("passed") is False:
        if prev.get("continued_from") is not None and (prev_dir / "start.pt").exists():
            # Keep the last good generator: the one the failed run started from.
            return {"start_from": str(prev_dir / "start.pt"), "continued_from": prev.get("continued_from"),
                    "reason": f"run {prev_n} failed its regression gate; restarting from the generator it "
                              f"started from (last passed in run {prev.get('continued_from')})"}
        return {**fresh, "reason": f"run {prev_n} failed its regression gate and started fresh itself"}
    return {**fresh, "reason": f"run {prev_n} has no regression-gate result"}
