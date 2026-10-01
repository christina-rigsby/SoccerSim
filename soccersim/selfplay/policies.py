"""Policy specs: serialisable descriptions of who plays, built inside worker processes.

A spec is a plain dict so it can cross a ``multiprocessing`` boundary:

- ``{"id": "library", "kind": "library", "temperature": 0.05}`` — Modules 1+2, library plays only.
- ``{"id": "high_press", "kind": "style", "style": "high_press"}`` — a scripted league opponent
  with fixed play weights from ``configs/league.yaml`` (spec §11).
- ``{"id": "main@12", "kind": "agent", "checkpoint": "<dir>", "generator": true, "critic": true}`` —
  the learning agent: critic in the ranking score, generated plays in the candidate set.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from ..config import load_config
from ..ranking.selector import RankingPolicy
from ..schema.models import Play


def style_bonus(style: str, league_cfg: dict | None = None) -> dict[str, float]:
    cfg = league_cfg or load_config("league")
    return dict(cfg["scripted_styles"][style]["favour"])


def make_policy(spec: dict[str, Any], library: dict[str, Play], rng: np.random.Generator) -> RankingPolicy:
    kind = spec.get("kind", "library")
    temp = spec.get("temperature")
    if kind == "library":
        return RankingPolicy(library, rng=rng, temperature=temp, name=spec.get("id", "library"))
    if kind == "style":
        return RankingPolicy(library, rng=rng, temperature=temp, style=style_bonus(spec["style"]),
                             name=spec.get("id", spec["style"]))
    if kind == "agent":
        from ..generator.agent import make_agent_policy

        return make_agent_policy(spec, library, rng)
    raise ValueError(f"unknown policy kind {kind!r}")
