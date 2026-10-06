"""Policy specs: serialisable descriptions of who plays, built inside worker processes.

A spec is a plain dict so it can cross a ``multiprocessing`` boundary:

- ``{"id": "library", "kind": "library", "temperature": 0.05}`` — Modules 1+2, library plays only.
- ``{"id": "high_press", "kind": "style", "style": "high_press", "temperature": 0.01}`` — a
  scripted league opponent with fixed play preferences from ``configs/league.yaml`` (spec §11);
  build it with :func:`style_spec` so the style's own temperature is used.
- ``{"id": "main@12", "kind": "agent", "checkpoint": "<dir>", "generator": true, "critic": true}`` —
  the learning agent: critic in the ranking score, generated plays in the candidate set.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from ..config import load_config
from ..ranking.selector import RankingPolicy
from ..schema.models import Play

DEFAULT_STYLE_TEMPERATURE = 0.01


def style_bonus(style: str, league_cfg: dict | None = None) -> dict[str, float]:
    """Per-play score bonus of a scripted style (negative = the style avoids that play)."""
    cfg = league_cfg or load_config("league")
    return dict(cfg["scripted_styles"][style].get("favour") or {})


def style_temperature(style: str, league_cfg: dict | None = None) -> float:
    cfg = league_cfg or load_config("league")
    return float(cfg["scripted_styles"][style].get("temperature", DEFAULT_STYLE_TEMPERATURE))


def style_spec(style: str, league_cfg: dict | None = None) -> dict[str, Any]:
    """Policy spec of a scripted style, with the style's own selection temperature."""
    return {"id": style, "kind": "style", "style": style, "temperature": style_temperature(style, league_cfg)}


def check_styles(league_cfg: dict, library: dict[str, Play]) -> None:
    """Every play a style favours or avoids must exist, and held-out styles must be styles."""
    styles = league_cfg["scripted_styles"]
    for name, st in styles.items():
        unknown = sorted(set(st.get("favour") or {}) - set(library))
        if unknown:
            raise ValueError(f"style {name!r} refers to unknown plays: {', '.join(unknown)}")
    missing = sorted(set(league_cfg["held_out_styles"]) - set(styles))
    if missing:
        raise ValueError(f"held-out styles are not defined: {', '.join(missing)}")
    if not set(styles) - set(league_cfg["held_out_styles"]):
        raise ValueError("every scripted style is held out; nothing left to train against")


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
