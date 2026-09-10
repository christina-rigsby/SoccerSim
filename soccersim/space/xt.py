"""Expected-threat surface — the value of having the ball at each point.

.. warning::
   The default surface is an **uncalibrated analytic prior** (D-015; see Q-006). Its
   *shape* is right — monotone toward goal, symmetric about the centre line, bounded —
   and its *magnitudes* are meaningless. Downstream code may depend on the shape. Do
   not tune soft-constraint coefficients against it (Q-014); that would be fitting to a
   fiction.

Everything goes through the :class:`ThreatSurface` protocol so a surface fitted from
SoccerNet, or a published xT grid, can replace the prior without touching callers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

import numpy as np

from ..domain.pitch import Pitch
from .grid import PitchGrid


@runtime_checkable
class ThreatSurface(Protocol):
    """Anything that can value pitch locations for a team attacking one way."""

    def value(self, points, attacking_direction: int): ...


@dataclass
class AnalyticThreatSurface:
    """Placeholder xT prior: ``exp(-d / decay) * 1 / (1 + (|y| / half_width)^2)``.

    ``d`` is distance to the attacked goal's centre. The two factors encode the only two
    facts the prior claims to know: threat rises sharply as you approach goal, and falls
    off toward the touchlines.
    """

    pitch: Pitch = field(default_factory=Pitch)
    #: Metres over which threat falls by a factor of e as you retreat from goal.
    decay: float = 18.0
    #: Lateral distance at which the centrality factor halves.
    half_width: float = 16.0

    def value(self, points, attacking_direction: int = 1):
        """Threat at point(s), in ``(0, 1]``. Accepts ``(2,)`` or ``(..., 2)``."""
        p = np.asarray(points, dtype=float)
        distance = self.pitch.distance_to_goal(p, attacking_direction)
        centrality = 1.0 / (1.0 + (np.abs(p[..., 1]) / self.half_width) ** 2)
        threat = np.exp(-distance / self.decay) * centrality
        return float(threat) if p.ndim == 1 else threat

    def field(self, grid: PitchGrid, attacking_direction: int = 1) -> np.ndarray:
        """The surface sampled on ``grid``, shape ``(ny, nx)``."""
        return np.asarray(self.value(grid.points(), attacking_direction))


@dataclass
class GriddedThreatSurface:
    """A threat surface backed by tabulated values — the shape a fitted surface takes.

    Provided so that closing Q-006 is a matter of loading data rather than rewriting
    callers. Values are given for ``attacking_direction = +1`` and mirrored when a team
    attacks the other way.
    """

    grid: PitchGrid
    values: np.ndarray

    def __post_init__(self) -> None:
        self.values = np.asarray(self.values, dtype=float)
        if self.values.shape != self.grid.shape:
            raise ValueError(
                f"values shape {self.values.shape} does not match grid {self.grid.shape}"
            )

    def value(self, points, attacking_direction: int = 1):
        p = np.asarray(points, dtype=float)
        flat = p.reshape(-1, 2).copy()
        if attacking_direction < 0:
            flat[:, 0] *= -1.0  # mirror into the +1 frame the table is stored in
        out = np.array([self.values[self.grid.index_of(pt)] for pt in flat])
        return float(out[0]) if p.ndim == 1 else out.reshape(p.shape[:-1])

    def field(self, grid: PitchGrid, attacking_direction: int = 1) -> np.ndarray:
        return np.asarray(self.value(grid.points(), attacking_direction))


def threat_gain(
    surface: ThreatSurface,
    origin,
    destination,
    attacking_direction: int = 1,
) -> float:
    """Change in threat from moving the ball ``origin -> destination``.

    This, not the absolute value, is what play ranking cares about: a play is worth
    running to the extent that it improves where the ball is.
    """
    start = surface.value(origin, attacking_direction)
    end = surface.value(destination, attacking_direction)
    return float(end) - float(start)
