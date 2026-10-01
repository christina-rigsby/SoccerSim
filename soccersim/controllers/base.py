"""Controller interface (spec §7.3).

A controller turns one action plus live state into a :class:`Directive` for one player:
a steering target and speed, optionally a ball command, and a defensive mode that sets
tackle rates. Controllers work in the team's attacking frame; the env converts to
absolute coordinates. Completion is reported by setting ``mem["done"] = True``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..dashboard.evaluator import Evaluator
from ..dashboard.team_state import TeamView


@dataclass
class FrameBallCommand:
    kind: str                       # pass | shoot | clear
    target: np.ndarray              # team frame
    style: str = "ground"
    receiver: int = -1
    placement: str = "auto"


@dataclass
class Directive:
    target: np.ndarray              # team frame
    speed: float = 1.0              # fraction of max speed
    ball: FrameBallCommand | None = None
    mode: str = "default"           # press | tackle | jockey | none | default
    protect: bool = False
    label: str = ""                 # action type, for the replay viewer


@dataclass
class ControllerCtx:
    view: TeamView
    ev: Evaluator
    cfg: dict                       # sim config
    role: str = ""
    group: list[int] = field(default_factory=list)
    marked: set[int] = field(default_factory=set)
    #: role -> that role's current steering target (previous tick), for arrive_with timing.
    role_targets: dict[str, np.ndarray] = field(default_factory=dict)


Controller = Callable[[ControllerCtx, int, dict[str, Any], dict[str, Any]], Directive]
REGISTRY: dict[str, Controller] = {}


def controller(*types: str):
    def deco(fn: Controller) -> Controller:
        for t in types:
            REGISTRY[t] = fn
        return fn
    return deco


SPEED = {"jog": 0.55, "fast": 0.8, "max": 1.0}


def speed_of(params: dict, default: str = "fast") -> float:
    return SPEED.get(params.get("speed", default), 0.8)


def hold(ctx: ControllerCtx, player: int, label: str = "hold", protect: bool = False) -> Directive:
    """Stand still (the "hold position facing the ball" state of spec §4.3)."""
    return Directive(ctx.view.pos[player].copy(), 0.0, label=label, protect=protect)


def clip_pitch(p: np.ndarray, margin: float = 0.5) -> np.ndarray:
    return np.array([np.clip(p[0], -52.5 + margin, 52.5 - margin), np.clip(p[1], -34 + margin, 34 - margin)])


def arrived(ctx: ControllerCtx, player: int, point: np.ndarray, radius: float | None = None) -> bool:
    r = ctx.cfg["movement"]["arrive_radius"] if radius is None else radius
    return float(np.hypot(*(ctx.view.pos[player] - point))) <= r


def move_target(ctx: ControllerCtx, player: int, target: dict, mem: dict[str, Any], key: str = "to"):
    """Resolve a movement target with the right refresh policy.

    Targets anchored on the ball, the ball holder, or the mover's own role are resolved
    once when the action is issued (otherwise a carry "3 m ahead of the ball" would chase
    itself forever). Pitch-control-maximising targets refresh every 0.5 s so they do not
    jitter cell to cell. Everything else is live, per spec §3.3.
    """
    t = ctx.view.t
    anchor = target.get("anchor") if isinstance(target, dict) else None
    self_anchored = anchor in ("ball", "ball_holder") or anchor == f"role:{ctx.role}"
    slow = isinstance(target, dict) and ("zone" in target or "pc_best" in target)
    cache = mem.get(f"_{key}")
    if cache is not None and (self_anchored or (slow and t - cache[2] < 0.5)):
        return cache[0], cache[1]
    pt, who = ctx.ev.target(target)
    if pt is not None:
        pt = clip_pitch(pt)
        if self_anchored or slow:
            mem[f"_{key}"] = (pt, who, t)
    return pt, who


def nearest_teammate_to(ctx: ControllerCtx, point: np.ndarray, exclude: int) -> int:
    v = ctx.view
    pool = [int(i) for i in v.us if i != exclude and v.state.kinds[i] != "GK"]
    t = np.linalg.norm(v.pos[pool] - point, axis=1) / v.vmax[pool]
    return pool[int(np.argmin(t))]
