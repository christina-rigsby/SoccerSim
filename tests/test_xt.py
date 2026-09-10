"""Expected-threat surface.

The default surface is an uncalibrated prior (D-015 / Q-006), so these tests assert its
*shape* — monotone toward goal, symmetric about the centre line, bounded — and nothing
about its magnitudes. That is exactly the contract downstream code is allowed to rely
on, and it is what a fitted replacement will have to preserve.
"""

import numpy as np
import pytest

from soccersim.domain.pitch import Pitch, vec
from soccersim.space.grid import PitchGrid
from soccersim.space.xt import (
    AnalyticThreatSurface,
    GriddedThreatSurface,
    ThreatSurface,
    threat_gain,
)

SURFACE = AnalyticThreatSurface()
GRID = PitchGrid(Pitch(), 3.0)


class TestAnalyticSurface:
    def test_satisfies_the_protocol(self):
        assert isinstance(SURFACE, ThreatSurface)

    def test_increases_toward_goal_along_the_centre_line(self):
        values = [SURFACE.value(vec(x, 0.0), 1) for x in np.arange(-50.0, 52.5, 2.5)]
        assert all(later > earlier for earlier, later in zip(values, values[1:]))

    def test_symmetric_about_the_centre_line(self):
        for x in (-30.0, 0.0, 30.0, 50.0):
            for y in (5.0, 15.0, 30.0):
                assert SURFACE.value(vec(x, y), 1) == pytest.approx(
                    SURFACE.value(vec(x, -y), 1)
                )

    def test_decreases_toward_the_touchline(self):
        values = [SURFACE.value(vec(40.0, y), 1) for y in np.arange(0.0, 34.0, 2.0)]
        assert all(later < earlier for earlier, later in zip(values, values[1:]))

    def test_bounded_in_the_unit_interval(self):
        field = SURFACE.field(GRID, 1)
        assert field.min() > 0.0
        assert field.max() <= 1.0

    def test_attacking_direction_mirrors_the_surface(self):
        assert SURFACE.value(vec(40.0, 8.0), 1) == pytest.approx(
            SURFACE.value(vec(-40.0, 8.0), -1)
        )

    def test_the_two_directions_disagree_everywhere_but_the_halfway_line(self):
        assert SURFACE.value(vec(40.0, 0.0), 1) > SURFACE.value(vec(40.0, 0.0), -1)
        assert SURFACE.value(vec(0.0, 0.0), 1) == pytest.approx(
            SURFACE.value(vec(0.0, 0.0), -1)
        )

    def test_maximum_is_at_the_attacked_goal(self):
        field = SURFACE.field(GRID, 1)
        row, col = np.unravel_index(int(np.argmax(field)), field.shape)
        assert GRID.coord_of(int(row), int(col))[0] > 45.0
        assert abs(GRID.coord_of(int(row), int(col))[1]) < 3.0

    def test_scalar_in_scalar_out(self):
        assert isinstance(SURFACE.value(vec(0, 0), 1), float)

    def test_vectorises_over_points(self):
        points = np.array([[0.0, 0.0], [40.0, 0.0], [-40.0, 0.0]])
        assert np.asarray(SURFACE.value(points, 1)).shape == (3,)

    def test_field_matches_the_grid_shape(self):
        assert SURFACE.field(GRID, 1).shape == GRID.shape

    def test_shorter_decay_concentrates_threat_near_goal(self):
        near, far = vec(45.0, 0.0), vec(-20.0, 0.0)
        sharp = AnalyticThreatSurface(decay=8.0)
        broad = AnalyticThreatSurface(decay=40.0)
        assert sharp.value(far, 1) / sharp.value(near, 1) < broad.value(far, 1) / broad.value(
            near, 1
        )


class TestGriddedSurface:
    def test_reproduces_the_values_it_was_built_from(self):
        values = SURFACE.field(GRID, 1)
        gridded = GriddedThreatSurface(GRID, values)
        for point in (vec(40.0, 0.0), vec(-20.0, 10.0), vec(0.0, -30.0)):
            row, col = GRID.index_of(point)
            assert gridded.value(point, 1) == pytest.approx(values[row, col])

    def test_mirrors_for_the_other_direction(self):
        gridded = GriddedThreatSurface(GRID, SURFACE.field(GRID, 1))
        assert gridded.value(vec(40.0, 5.0), 1) == pytest.approx(
            gridded.value(vec(-40.0, 5.0), -1)
        )

    def test_rejects_a_mismatched_table(self):
        with pytest.raises(ValueError):
            GriddedThreatSurface(GRID, np.zeros((3, 3)))

    def test_satisfies_the_protocol(self):
        assert isinstance(GriddedThreatSurface(GRID, SURFACE.field(GRID, 1)), ThreatSurface)

    def test_vectorises_and_preserves_shape(self):
        gridded = GriddedThreatSurface(GRID, SURFACE.field(GRID, 1))
        points = np.zeros((2, 3, 2))
        assert np.asarray(gridded.value(points, 1)).shape == (2, 3)


class TestThreatGain:
    def test_progressing_the_ball_is_a_gain(self):
        assert threat_gain(SURFACE, vec(0.0, 0.0), vec(40.0, 0.0), 1) > 0

    def test_retreating_is_a_loss(self):
        assert threat_gain(SURFACE, vec(40.0, 0.0), vec(0.0, 0.0), 1) < 0

    def test_moving_nowhere_is_neutral(self):
        assert threat_gain(SURFACE, vec(20.0, 5.0), vec(20.0, 5.0), 1) == pytest.approx(0.0)

    def test_gain_is_antisymmetric(self):
        there = threat_gain(SURFACE, vec(-10.0, 4.0), vec(35.0, -8.0), 1)
        back = threat_gain(SURFACE, vec(35.0, -8.0), vec(-10.0, 4.0), 1)
        assert there == pytest.approx(-back)

    def test_a_square_ball_into_the_middle_gains_over_staying_wide(self):
        """Sanity check the centrality term does something football-shaped."""
        assert threat_gain(SURFACE, vec(40.0, 30.0), vec(40.0, 0.0), 1) > 0
