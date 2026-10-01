"""Zones in the attacking frame with side-relative lanes (spec §3.1), and the 2 m grid.

``side`` is the frozen ball side (+1 / -1); ``ys = y * side`` so "near" always means the
ball-side touchline and every play mirrors automatically.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np

from ..schema.vocab import BANDS, LANES

HALF_L, HALF_W = 52.5, 34.0

#: Pitch-control grid: 53 x 34 cells of ~2 m (spec §8.4).
GRID_NX, GRID_NY = 53, 34
_xs = -HALF_L + (np.arange(GRID_NX) + 0.5) * (2 * HALF_L / GRID_NX)
_ys = -HALF_W + (np.arange(GRID_NY) + 0.5) * (2 * HALF_W / GRID_NY)
GRID_X, GRID_Y = _xs, _ys
_gx, _gy = np.meshgrid(_xs, _ys)
GRID_POINTS = np.stack([_gx.ravel(), _gy.ravel()], axis=1)  # (GRID_NY * GRID_NX, 2), row-major in y


def _in(v: np.ndarray, lo: float, hi: float, top_inclusive: bool) -> np.ndarray:
    return (v >= lo) & ((v <= hi) if top_inclusive else (v < hi))


def zone_mask(points: np.ndarray, zone: str, side: float) -> np.ndarray:
    """Boolean mask of ``points`` (frame, ``(N, 2)``) inside ``zone``."""
    p = np.atleast_2d(np.asarray(points, dtype=float))
    x = np.clip(p[:, 0], -HALF_L, HALF_L)
    y = np.clip(p[:, 1], -HALF_W, HALF_W)
    ys = y * side
    ay = np.abs(y)
    if zone == "box":
        return (x >= 36.0) & (ay <= 20.16)
    if zone == "own_box":
        return (x <= -36.0) & (ay <= 20.16)
    if zone == "zone14":
        return (x >= 19.0) & (x < 36.0) & (np.abs(ys) <= 9.16)
    if zone == "cutback_zone":
        return (x >= 41.0) & (x < 47.0) & (np.abs(ys) <= 9.16)
    if zone == "near_post_area":
        return (x >= 47.0) & (x <= HALF_L) & (ys >= 0.0) & (ys <= 9.16)
    if zone == "far_post_area":
        return (x >= 44.0) & (x <= HALF_L) & (ys >= -12.0) & (ys < -1.0)
    if zone == "own_box_edge":
        return (x > -36.0) & (x <= -30.0) & (ay <= 20.16)
    band, lane = zone.split(".", 1)
    m = np.ones(len(p), dtype=bool)
    if band != "*":
        lo, hi = BANDS[band]
        m &= _in(x, lo, hi, top_inclusive=(band == "final_third"))
    if lane != "*":
        lo, hi = LANES[lane]
        m &= _in(ys, lo, hi, top_inclusive=(lane == "near_wing"))
    return m


def in_zones(points: np.ndarray, zones, side: float) -> np.ndarray:
    zs = zones if isinstance(zones, (list, tuple)) else [zones]
    m = np.zeros(len(np.atleast_2d(points)), dtype=bool)
    for z in zs:
        m |= zone_mask(points, z, side)
    return m


@lru_cache(maxsize=256)
def _grid_mask(zone: str, side: float) -> np.ndarray:
    return zone_mask(GRID_POINTS, zone, side)


def grid_mask(zone: str, side: float) -> np.ndarray:
    return _grid_mask(zone, float(side))


def zone_centroid(zone: str, side: float) -> np.ndarray:
    m = grid_mask(zone, side)
    if not m.any():
        return np.zeros(2)
    return GRID_POINTS[m].mean(axis=0)


def lane_center(lane: str, side: float) -> float:
    lo, hi = LANES[lane]
    return 0.5 * (lo + hi) * side


def zone_of(point: np.ndarray, side: float) -> str:
    """``band.lane`` id containing ``point`` (for descriptors and logs)."""
    for band in BANDS:
        for lane in LANES:
            z = f"{band}.{lane}"
            if zone_mask(point, z, side)[0]:
                return z
    return "mid_own.center"
