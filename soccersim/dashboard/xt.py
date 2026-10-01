"""Expected threat on a 16 x 12 grid (spec §8.4).

Starts as a distance/angle placeholder built from ``configs/xt_placeholder.yaml``. M6
replaces it with a value-iterated xT (Singh 2019) fitted from simulator move and shot
events (:func:`fit_xt`); the fitted grid is saved as JSON and picked up by
:func:`load_xt` when ``source: fitted``.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from ..config import REPO_ROOT, load_config
from ..sim.shots import goal_angle

HALF_L, HALF_W = 52.5, 34.0


class XTSurface:
    """Tabulated xT in the attacking frame; ``values`` is ``(ny, nx)``, row = y."""

    def __init__(self, values: np.ndarray, source: str = "placeholder") -> None:
        self.values = np.asarray(values, dtype=float)
        self.ny, self.nx = self.values.shape
        self.source = source

    def cell(self, points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        p = np.atleast_2d(np.asarray(points, dtype=float))
        col = np.clip(((p[:, 0] + HALF_L) / (2 * HALF_L) * self.nx).astype(int), 0, self.nx - 1)
        row = np.clip(((p[:, 1] + HALF_W) / (2 * HALF_W) * self.ny).astype(int), 0, self.ny - 1)
        return row, col

    def value(self, points):
        p = np.asarray(points, dtype=float)
        row, col = self.cell(p)
        out = self.values[row, col]
        return float(out[0]) if p.ndim == 1 else out

    def cell_centres(self) -> np.ndarray:
        xs = -HALF_L + (np.arange(self.nx) + 0.5) * (2 * HALF_L / self.nx)
        ys = -HALF_W + (np.arange(self.ny) + 0.5) * (2 * HALF_W / self.ny)
        gx, gy = np.meshgrid(xs, ys)
        return np.stack([gx, gy], axis=-1)

    def to_json(self) -> dict:
        return {"source": self.source, "values": np.round(self.values, 6).tolist()}


def placeholder_xt(cfg: dict | None = None) -> XTSurface:
    cfg = cfg or load_config("xt_placeholder")
    tmp = XTSurface(np.zeros((cfg["ny"], cfg["nx"])))
    c = tmp.cell_centres()
    dist = np.hypot(HALF_L - c[..., 0], c[..., 1])
    ang = goal_angle(c)
    val = cfg["peak"] * np.exp(-dist / cfg["decay_m"]) * (1.0 + cfg["angle_weight"] * ang) / (1.0 + cfg["angle_weight"])
    return XTSurface(np.maximum(val, cfg["floor"]), "placeholder")


def load_xt(cfg: dict | None = None) -> XTSurface:
    cfg = cfg or load_config("xt_placeholder")
    if cfg.get("source") == "fitted":
        path = REPO_ROOT / cfg.get("fitted_path", "data/xt/xt_sim.json")
        if path.exists():
            data = json.loads(path.read_text())
            return XTSurface(np.array(data["values"]), "fitted")
    return placeholder_xt(cfg)


def fit_xt(
    moves: np.ndarray,
    move_success: np.ndarray,
    shots: np.ndarray,
    goals: np.ndarray,
    nx: int = 16,
    ny: int = 12,
    prior: XTSurface | None = None,
    prior_weight: float = 5.0,
    iterations: int = 40,
) -> XTSurface:
    """Value-iterated xT from attacking-frame events.

    ``moves``: ``(M, 4)`` start/end points of passes and carries; ``move_success``:
    ``(M,)`` bool; ``shots``: ``(S, 2)``; ``goals``: ``(S,)`` bool. Cells with little data
    are shrunk toward ``prior`` with ``prior_weight`` pseudo-observations.
    """
    grid = XTSurface(np.zeros((ny, nx)))
    n = nx * ny

    def flat(points: np.ndarray) -> np.ndarray:
        if len(points) == 0:
            return np.zeros(0, dtype=int)
        r, c = grid.cell(points)
        return r * nx + c

    start = flat(moves[:, :2]) if len(moves) else np.zeros(0, dtype=int)
    end = flat(moves[:, 2:]) if len(moves) else np.zeros(0, dtype=int)
    shot_cells = flat(shots)
    move_count = np.bincount(start, minlength=n).astype(float)
    shot_count = np.bincount(shot_cells, minlength=n).astype(float)
    goal_count = np.bincount(shot_cells[goals.astype(bool)], minlength=n).astype(float) if len(shots) else np.zeros(n)
    total = move_count + shot_count
    p_shot = np.divide(shot_count, total, out=np.zeros(n), where=total > 0)
    p_move = np.divide(move_count, total, out=np.zeros(n), where=total > 0)
    p_goal = np.divide(goal_count, shot_count, out=np.zeros(n), where=shot_count > 0)
    trans = np.zeros((n, n))
    ok = move_success.astype(bool) if len(moves) else np.zeros(0, dtype=bool)
    np.add.at(trans, (start[ok], end[ok]), 1.0)
    trans = np.divide(trans, move_count[:, None], out=np.zeros_like(trans), where=move_count[:, None] > 0)

    xt = np.zeros(n)
    for _ in range(iterations):
        xt = p_shot * p_goal + p_move * (trans @ xt)
    values = xt.reshape(ny, nx)
    if prior is not None:
        pv = prior.values if prior.values.shape == values.shape else placeholder_xt().values
        w = (total / (total + prior_weight)).reshape(ny, nx)
        values = w * values + (1 - w) * pv
    return XTSurface(values, "fitted")


def save_xt(surface: XTSurface, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(surface.to_json()))
