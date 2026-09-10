"""Pitch geometry and the project's coordinate convention.

Coordinate convention (D-012): metres, origin at the centre mark, ``x`` along the
length of the pitch and ``y`` across it, so a full-size pitch spans
``x in [-52.5, 52.5]`` and ``y in [-34, 34]``.

A team's ``attacking_direction`` is ``+1`` or ``-1`` and multiplies ``x``, so a single
code path handles both halves. Signed ``y`` means centrality and mirror-symmetry are
expressible as ``f(y) == f(-y)``, which is how most geometry tests are written.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# IFAB permits a range; these are the standard professional dimensions.
DEFAULT_LENGTH = 105.0
DEFAULT_WIDTH = 68.0


def vec(x: float, y: float) -> np.ndarray:
    """A 2-D point/vector in pitch coordinates."""
    return np.array([float(x), float(y)], dtype=float)


@dataclass(frozen=True)
class Pitch:
    """Pitch dimensions and derived markings.

    All markings are derived rather than stored so that a non-standard pitch size
    stays internally consistent.
    """

    length: float = DEFAULT_LENGTH
    width: float = DEFAULT_WIDTH
    goal_width: float = 7.32
    penalty_box_depth: float = 16.5
    penalty_box_width: float = 40.32
    goal_area_depth: float = 5.5
    goal_area_width: float = 18.32
    centre_circle_radius: float = 9.15
    penalty_spot_distance: float = 11.0

    # -- extents ---------------------------------------------------------------

    @property
    def half_length(self) -> float:
        return self.length / 2.0

    @property
    def half_width(self) -> float:
        return self.width / 2.0

    @property
    def x_bounds(self) -> tuple[float, float]:
        return -self.half_length, self.half_length

    @property
    def y_bounds(self) -> tuple[float, float]:
        return -self.half_width, self.half_width

    # -- goals -----------------------------------------------------------------

    def goal_centre(self, attacking_direction: int) -> np.ndarray:
        """Centre of the goal a team attacking in ``attacking_direction`` shoots at."""
        return vec(np.sign(attacking_direction) * self.half_length, 0.0)

    def goal_posts(self, attacking_direction: int) -> tuple[np.ndarray, np.ndarray]:
        """The two posts of that goal, ordered by ``y``."""
        gx = np.sign(attacking_direction) * self.half_length
        half = self.goal_width / 2.0
        return vec(gx, -half), vec(gx, half)

    # -- containment -----------------------------------------------------------

    def contains(self, point) -> bool | np.ndarray:
        """Whether point(s) lie within the field of play (touchlines inclusive).

        Accepts a single ``(2,)`` point or an ``(..., 2)`` array.
        """
        p = np.asarray(point, dtype=float)
        inside = (np.abs(p[..., 0]) <= self.half_length + 1e-9) & (
            np.abs(p[..., 1]) <= self.half_width + 1e-9
        )
        return bool(inside) if p.ndim == 1 else inside

    def in_penalty_box(self, point, attacking_direction: int) -> bool | np.ndarray:
        """Whether point(s) lie in the penalty box being attacked."""
        p = np.asarray(point, dtype=float)
        s = np.sign(attacking_direction)
        depth_from_goal = self.half_length - s * p[..., 0]
        inside = (
            (depth_from_goal >= -1e-9)
            & (depth_from_goal <= self.penalty_box_depth + 1e-9)
            & (np.abs(p[..., 1]) <= self.penalty_box_width / 2.0 + 1e-9)
        )
        return bool(inside) if p.ndim == 1 else inside

    # -- zones -----------------------------------------------------------------

    def third(self, point, attacking_direction: int) -> str:
        """``"defensive"``, ``"middle"`` or ``"final"`` third, from the team's view."""
        p = np.asarray(point, dtype=float)
        progress = np.sign(attacking_direction) * p[0]
        cut = self.half_length / 3.0
        if progress < -cut:
            return "defensive"
        if progress > cut:
            return "final"
        return "middle"

    def channel(self, point) -> str:
        """Lateral channel: ``"left"``, ``"left_half"``, ``"centre"``, ... .

        Five channels, as used in positional-play terminology. ``left`` is negative
        ``y`` — direction-agnostic, so callers that care about a team's own left must
        account for ``attacking_direction`` themselves.
        """
        p = np.asarray(point, dtype=float)
        # Wide channels are the width of the penalty box's overhang; half-spaces sit
        # between the box edge and the goal-area edge extended upfield.
        wide_edge = self.penalty_box_width / 2.0
        half_edge = self.goal_area_width / 2.0
        y = p[1]
        if y < -wide_edge:
            return "left"
        if y < -half_edge:
            return "left_half"
        if y <= half_edge:
            return "centre"
        if y <= wide_edge:
            return "right_half"
        return "right"

    def distance_to_goal(self, point, attacking_direction: int):
        """Euclidean distance from point(s) to the attacked goal's centre."""
        p = np.asarray(point, dtype=float)
        goal = self.goal_centre(attacking_direction)
        return np.linalg.norm(p - goal, axis=-1)
