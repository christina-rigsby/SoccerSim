"""Pitch control — who would get to each point first.

Model (D-013, provisional; see Q-005)::

    control = sigmoid(lambda * (t_defence_best - t_attack_best))

with arrival times from :mod:`soccersim.kinematics`. A team that reaches a point a
second sooner than anyone in the other team holds roughly 82% control of it at the
default sharpness.

Why not plain distance Voronoi: it is momentum-blind, so it cannot distinguish a
settled defensive block from a defence caught facing the wrong way — which is exactly
the situation counter-attacking strategies exist to exploit.

Why not the full Spearman pass-probability model: it needs pass-completion data to
calibrate, and none exists in the project yet.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..domain.entities import Team
from ..domain.state import GameState
from ..kinematics import best_time_to_point
from .grid import PitchGrid

#: Sharpness of the control transition, per second of arrival-time advantage.
#: Uncalibrated (Q-005): at 1.5, a 1 s advantage reads as ~82% control and a 0.25 s
#: advantage as ~59%.
DEFAULT_SHARPNESS = 1.5


def _sigmoid(z: np.ndarray) -> np.ndarray:
    """Logistic function, computed branch-wise so ``+/-inf`` saturate instead of overflowing."""
    z = np.asarray(z, dtype=float)
    out = np.empty_like(z)
    positive = z >= 0
    out[positive] = 1.0 / (1.0 + np.exp(-z[positive]))
    exp_z = np.exp(z[~positive])
    out[~positive] = exp_z / (1.0 + exp_z)
    return out


@dataclass
class ControlField:
    """A pitch-control field for one team, plus the arrival times behind it.

    Keeping the arrival times means downstream code can ask "by how much?" and not only
    "who?" — the ``max_speed`` hard constraint and any contest-margin soft constraint
    both want the margin, not the winner.
    """

    team: Team
    grid: PitchGrid
    control: np.ndarray  # (ny, nx) in [0, 1]; 1 = fully this team's space
    attack_time: np.ndarray  # (ny, nx) fastest arrival for `team`
    defence_time: np.ndarray  # (ny, nx) fastest arrival for the opponent

    @property
    def advantage(self) -> np.ndarray:
        """Arrival-time advantage in seconds; positive means ``team`` gets there first."""
        return self.defence_time - self.attack_time

    def at(self, point) -> float:
        """Control value at the cell containing ``point``."""
        row, col = self.grid.index_of(point)
        return float(self.control[row, col])

    def controlled_area(self, threshold: float = 0.5) -> float:
        """Area in m^2 where control exceeds ``threshold``."""
        return float((self.control > threshold).sum() * self.grid.cell_area)

    def best_point(self, mask: np.ndarray | None = None) -> np.ndarray:
        """Coordinate of maximum control, optionally restricted by a boolean ``mask``."""
        field = self.control if mask is None else np.where(mask, self.control, -np.inf)
        row, col = np.unravel_index(int(np.argmax(field)), field.shape)
        return self.grid.coord_of(int(row), int(col))


def control_field(
    state: GameState,
    team: Team = Team.HOME,
    grid: PitchGrid | None = None,
    sharpness: float = DEFAULT_SHARPNESS,
) -> ControlField:
    """Compute the pitch-control field from ``team``'s point of view.

    Only *available* players contribute — a sent-off or injured player claims no space.
    """
    grid = grid or PitchGrid(state.pitch)
    targets = grid.points()

    attack_time = np.asarray(best_time_to_point(state.team_state(team).available(), targets))
    defence_time = np.asarray(
        best_time_to_point(state.opponents_of(team).available(), targets)
    )

    # Both teams empty (or both unreachable) leaves the advantage undefined rather
    # than neutral; call it an even split instead of propagating NaN into every
    # consumer. inf - inf is expected here, so the warning is not informative.
    with np.errstate(invalid="ignore"):
        advantage = defence_time - attack_time
    advantage = np.where(np.isnan(advantage), 0.0, advantage)
    control = _sigmoid(sharpness * advantage)

    return ControlField(
        team=team,
        grid=grid,
        control=control,
        attack_time=attack_time,
        defence_time=defence_time,
    )


def control_gain_along(field: ControlField, points) -> np.ndarray:
    """Control values sampled at arbitrary ``points``.

    Convenience for waypoint definitions of the "point of maximum pitch-control gain
    along the flank" kind (design doc §3, D-003).
    """
    pts = np.asarray(points, dtype=float).reshape(-1, 2)
    return np.array([field.at(p) for p in pts])
