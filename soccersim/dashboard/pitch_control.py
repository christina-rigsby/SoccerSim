"""Vectorised pitch control on the 53 x 34 grid (spec §8.4).

Spearman-style time-to-intercept: each player's arrival time at a point is reaction time
plus straight-line distance from their reaction-projected position at top speed.
``control = sigmoid(sharpness * (t_them_best - t_us_best))`` — the same functional form
as D-013, so symmetric setups give exactly 0.5.
"""

from __future__ import annotations

import numpy as np

from ..sim.passmodel import arrival_times


def pitch_control(
    points: np.ndarray,
    us_pos: np.ndarray, us_vel: np.ndarray, us_vmax: np.ndarray,
    them_pos: np.ndarray, them_vel: np.ndarray, them_vmax: np.ndarray,
    reaction: float = 0.7,
    sharpness: float = 1.5,
) -> np.ndarray:
    pts = np.atleast_2d(points)
    t_us = arrival_times(pts, us_pos, us_vel, us_vmax, reaction).min(axis=0)
    t_them = arrival_times(pts, them_pos, them_vel, them_vmax, reaction).min(axis=0)
    return 1.0 / (1.0 + np.exp(-np.clip(sharpness * (t_them - t_us), -30, 30)))
