"""A shared discretisation of the pitch.

Pitch control, the threat surface, and any other field quantity all sample the same
grid, so they can be combined cell-wise without resampling.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..domain.pitch import Pitch


@dataclass
class PitchGrid:
    """Cell-centred grid over the field of play.

    ``resolution`` is the *requested* cell edge length in metres. It is rounded to a
    whole number of cells per axis, so the realised steps (``step_x``, ``step_y``) may
    differ slightly and are what geometry should use. Cells are centred, so no sample
    point sits exactly on a touchline — which keeps boundary-condition questions out of
    the field computations.
    """

    pitch: Pitch = field(default_factory=Pitch)
    resolution: float = 2.0

    def __post_init__(self) -> None:
        if self.resolution <= 0:
            raise ValueError("resolution must be positive")
        self.xs, self.step_x = self._centres(self.pitch.length)
        self.ys, self.step_y = self._centres(self.pitch.width)

    def _centres(self, extent: float) -> tuple[np.ndarray, float]:
        n = max(1, int(round(extent / self.resolution)))
        step = extent / n
        return -extent / 2.0 + step * (np.arange(n) + 0.5), step

    @property
    def shape(self) -> tuple[int, int]:
        """``(ny, nx)`` — row-major, matching :meth:`points` and matplotlib's imshow."""
        return len(self.ys), len(self.xs)

    def points(self) -> np.ndarray:
        """``(ny, nx, 2)`` array of cell-centre coordinates."""
        gx, gy = np.meshgrid(self.xs, self.ys)
        return np.stack([gx, gy], axis=-1)

    def flat_points(self) -> np.ndarray:
        """``(ny * nx, 2)`` array of cell centres."""
        return self.points().reshape(-1, 2)

    @property
    def extent(self) -> tuple[float, float, float, float]:
        """``(xmin, xmax, ymin, ymax)`` for ``imshow``, covering full cells.

        Uses the realised steps, so this reproduces the pitch extents exactly.
        """
        return (
            float(self.xs[0] - self.step_x / 2.0),
            float(self.xs[-1] + self.step_x / 2.0),
            float(self.ys[0] - self.step_y / 2.0),
            float(self.ys[-1] + self.step_y / 2.0),
        )

    @property
    def cell_area(self) -> float:
        return float(self.step_x * self.step_y)

    def index_of(self, point) -> tuple[int, int]:
        """``(row, col)`` of the cell containing ``point``, clamped to the grid."""
        p = np.asarray(point, dtype=float)
        col = int(np.clip(np.argmin(np.abs(self.xs - p[0])), 0, len(self.xs) - 1))
        row = int(np.clip(np.argmin(np.abs(self.ys - p[1])), 0, len(self.ys) - 1))
        return row, col

    def coord_of(self, row: int, col: int) -> np.ndarray:
        """Centre coordinate of cell ``(row, col)``."""
        return np.array([self.xs[col], self.ys[row]], dtype=float)
