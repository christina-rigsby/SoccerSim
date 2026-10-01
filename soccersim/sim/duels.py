"""Dribble / tackle duels and first-touch control (spec §7.2)."""

from __future__ import annotations

import numpy as np

from .state import CAP_INDEX, MatchState


def tackle_success_prob(state: MatchState, defender: int, carrier: int, cfg: dict, protect: bool,
                        mode: str) -> float:
    dc = cfg["duel"]
    tack = state.caps[defender, CAP_INDEX["tackling"]]
    drib = state.caps[carrier, CAP_INDEX["dribbling"]]
    p = dc["base_success"] + dc["skill_gain"] * (tack - drib)
    if is_from_behind(state, defender, carrier):
        p -= dc["behind_penalty"]
    if protect:
        p -= dc["protect_penalty"]
    if mode == "tackle":
        p += 0.05
    return float(np.clip(p, 0.05, 0.9))


def is_from_behind(state: MatchState, defender: int, carrier: int) -> bool:
    """Defender approaching from behind the carrier's direction of travel."""
    v = state.vel[carrier]
    speed = float(np.hypot(*v))
    if speed < 1.0:
        return False
    rel = state.pos[defender] - state.pos[carrier]
    return float(np.dot(rel, v)) / (speed * max(float(np.hypot(*rel)), 1e-6)) < -0.5


def foul_prob(state: MatchState, defender: int, carrier: int, cfg: dict) -> float:
    dc = cfg["duel"]
    return dc["foul_prob_from_behind"] if is_from_behind(state, defender, carrier) else dc["foul_prob_on_fail"]


def control_prob(state: MatchState, player: int, ball_speed: float, nearest_opp: float, cfg: dict) -> float:
    cc = cfg["control"]
    ft = state.caps[player, CAP_INDEX["first_touch"]]
    p = (cc["base"] - cc["first_touch_weight"] * (1.0 - ft)
         - cc["speed_penalty_per_ms"] * max(0.0, ball_speed - cc["comfortable_speed"])
         - cc["pressure_penalty"] * np.exp(-nearest_opp / 2.0))
    return float(np.clip(p, 0.05, 0.99))
