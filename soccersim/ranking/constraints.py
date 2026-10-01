"""Candidate filtering: phase, cooldown, triggers and the hard gate (spec §9.1–9.2)."""

from __future__ import annotations

from ..dashboard.evaluator import Evaluator
from ..dashboard.team_state import TeamView
from ..schema.models import Play

ATTACK_PHASES = ("in_possession", "transition_attack", "set_piece")
DEFEND_PHASES = ("out_of_possession", "transition_defense")


def phases_for(view: TeamView) -> tuple[str, ...]:
    if view.possession == "us":
        return ATTACK_PHASES
    if view.possession == "them":
        return DEFEND_PHASES
    return ()


def in_cooldown(play: Play, cooldowns: dict[str, float], t: float) -> bool:
    return cooldowns.get(play.id, -1e9) > t


def triggers_hold(play: Play, ev: Evaluator) -> bool:
    return ev.pred(play.triggers)


def hard_gate(play: Play, ev: Evaluator) -> str:
    """Empty string if every hard constraint holds, else the first failing one."""
    for i, hc in enumerate(play.hard_constraints):
        if not ev.pred(hc):
            return f"hard_constraints[{i}]"
    return ""
