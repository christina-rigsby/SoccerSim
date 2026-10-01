"""Shots: xG model and outcome sampling with a goalkeeper save model (spec §7.2 Shots).

All functions take positions in the shooter's attacking frame (goal at x = +52.5).
"""

from __future__ import annotations

import numpy as np

GOAL_X = 52.5


def goal_angle(pos: np.ndarray, goal_width: float = 7.32) -> np.ndarray:
    """Angle (radians) subtended by the goal mouth from ``pos`` (``(..., 2)``)."""
    p = np.asarray(pos, dtype=float)
    dx = np.maximum(GOAL_X - p[..., 0], 0.05)
    half = goal_width / 2.0
    a1 = np.arctan2(half - p[..., 1], dx)
    a2 = np.arctan2(-half - p[..., 1], dx)
    return np.abs(a1 - a2)


def xg(pos, pressure: float | np.ndarray = 0.0, header: bool = False, cfg: dict | None = None):
    """xG = sigmoid(b0 + b_angle * angle - b_dist * distance), reduced by pressure/air."""
    sc = (cfg or {}).get("shot", {}) or {}
    b0, ba, bd = sc.get("b0", -0.5), sc.get("b_angle", 1.5), sc.get("b_dist", 0.13)
    p = np.asarray(pos, dtype=float)
    dist = np.hypot(GOAL_X - p[..., 0], p[..., 1])
    logit = b0 + ba * goal_angle(p) - bd * dist
    val = 1.0 / (1.0 + np.exp(-logit))
    val = val * (1.0 - sc.get("pressure_factor", 0.4) * np.asarray(pressure))
    if header:
        val = val * sc.get("header_factor", 0.6)
    # Behind the goal line or beyond max range the shot is worthless.
    val = np.where((p[..., 0] >= GOAL_X) | (dist > sc.get("max_range", 35.0)), 0.0, val)
    return float(val) if np.ndim(val) == 0 else val


def gk_factor(shooter: np.ndarray, gk: np.ndarray | None, cfg: dict) -> float:
    """Multiplier on goal probability from goalkeeper positioning.

    The ideal keeper stands on the line from the shot to the goal centre, ~3 m off the
    line. Misplacement (distance from that point) raises the factor.
    """
    sc = cfg["shot"]
    if gk is None:
        return sc["gk_factor_max"]
    goal = np.array([GOAL_X, 0.0])
    to_goal = goal - shooter
    dist = float(np.hypot(*to_goal))
    ideal = goal - to_goal / max(dist, 1e-6) * min(3.0, dist * 0.5)
    miss = float(np.hypot(*(gk - ideal)))
    f = sc["gk_factor_min"] + 0.5 * miss / sc["gk_offset_scale"]
    return float(np.clip(f, sc["gk_factor_min"], sc["gk_factor_max"]))


def goal_probability(xg_value: float, finishing: float, gk_mult: float, cfg: dict) -> float:
    sc = cfg["shot"]
    p = xg_value * (sc["finishing_base"] + sc["finishing_gain"] * finishing) * gk_mult
    return float(np.clip(p, 0.0, 0.95))


def sample_outcome(rng: np.random.Generator, p_goal: float, cfg: dict) -> str:
    """goal | caught | parried_corner | off_target."""
    sc = cfg["shot"]
    if rng.random() < p_goal:
        return "goal"
    if rng.random() < sc["on_target_prob"]:
        return "caught" if rng.random() < sc["save_catch_prob"] / (sc["save_catch_prob"] + sc["corner_from_save"]) \
            else "parried_corner"
    return "off_target"


def shot_target(rng: np.random.Generator, outcome: str, shooter: np.ndarray, gk: np.ndarray | None,
                placement: str) -> np.ndarray:
    """Where the ball goes for a sampled outcome (shooter frame)."""
    near = 1.0 if shooter[1] >= 0 else -1.0
    side = near if placement == "near" else -near if placement == "far" else float(rng.choice([-1.0, 1.0]))
    if outcome == "goal":
        return np.array([GOAL_X + 1.0, side * rng.uniform(0.8, 3.2)])
    if outcome in ("caught", "parried_corner") and gk is not None:
        return gk.copy()
    return np.array([GOAL_X + 2.0, side * rng.uniform(4.2, 9.0)])
