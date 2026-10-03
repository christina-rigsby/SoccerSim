"""Loading plays from ``plays/**/*.yaml`` (one play per file, spec §4)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ..config import PLAYS_DIR
from .models import Play
from .validate import PlayValidationError, parse_play


def load_play_file(path: str | Path) -> Play:
    path = Path(path)
    with open(path) as fh:
        data = yaml.safe_load(fh)
    return parse_play(data, source=str(path))


PROMOTED_SUBDIR = "generated_and_promoted"


def load_library(
    root: str | Path | None = None,
    include: tuple[str, ...] = ("offensive", "defensive"),
    promoted_runs: list[int] | tuple[int, ...] | None = None,
) -> dict[str, Play]:
    """Load every play under ``root/<include>/``, plus promoted plays read in place.

    ``promoted_runs``: runs under ``root/generated_and_promoted/run_<N>/`` whose plays join
    the library. Defaults to ``configs/library.yaml`` for the shipped library and to none
    when ``root`` is given. Promoted plays keep their provenance (with ``run`` and
    ``adopted_into_library``) and are treated exactly like hand-written plays
    (``source: library``). Ids must be unique.
    """
    base = Path(root) if root else PLAYS_DIR
    lib_cfg = _library_config()
    if promoted_runs is None:
        promoted_runs = [int(r) for r in (lib_cfg.get("promoted_runs") or [])] if root is None else ()
    min_cooldown = float(lib_cfg.get("adopted_min_cooldown_s", 8.0))
    plays: dict[str, Play] = {}

    def add(play: Play, path: Path) -> None:
        if play.id in plays:
            raise PlayValidationError(play.id, ["duplicate play id in library"], str(path))
        plays[play.id] = play

    for sub in include:
        for path in sorted((base / sub).glob("*.yaml")):
            add(load_play_file(path), path)
    for run in promoted_runs:
        for path in sorted((base / PROMOTED_SUBDIR / f"run_{int(run)}").glob("*.yaml")):
            with open(path) as fh:
                data = yaml.safe_load(fh)
            add(parse_play(adopt_promoted(data, int(run), min_cooldown), source=str(path)), path)
    return plays


def adopt_promoted(data: dict[str, Any], run: int, min_cooldown_s: float = 8.0) -> dict[str, Any]:
    """A promoted play as a library play: ``source: library``, provenance kept, its
    triggers narrowed to the archive niche (start band and lane) it was promoted in, and a
    cooldown of at least ``min_cooldown_s``.

    Generated plays carry almost no triggers of their own; the niche is where the play was
    shown to beat the library's median, so outside it the play is unproven. The file on
    disk is not changed.
    """
    data = dict(data)
    prov = {**(data.get("provenance") or {}), "run": run, "adopted_into_library": True}
    cell = prov.get("archive_cell") or {}
    if cell.get("band") and cell.get("lane"):
        niche = {"ball_in_zone": [f"{cell['band']}.{cell['lane']}"]}
        trig = data.get("triggers")
        data["triggers"] = {"all": [trig, niche]} if trig not in (None, "always") else niche
        prov["library_niche"] = niche["ball_in_zone"][0]
    data["cooldown_s"] = max(float(data.get("cooldown_s") or 0.0), min_cooldown_s)
    data["source"] = "library"
    data["provenance"] = prov
    return data


def _library_config() -> dict[str, Any]:
    from ..config import CONFIG_DIR, load_config

    return load_config("library") if (CONFIG_DIR / "library.yaml").exists() else {}


def play_to_dict(play: Play) -> dict[str, Any]:
    """Serialise a play back to a YAML-ready mapping (actions keep their params inline)."""
    data = play.model_dump(mode="json", exclude_none=True)
    # Defaults that add noise without information.
    if not data.get("fallback"):
        data.pop("fallback", None)
    return data


def play_to_yaml(play: Play) -> str:
    return yaml.safe_dump(play_to_dict(play), sort_keys=False, default_flow_style=None, width=110)
