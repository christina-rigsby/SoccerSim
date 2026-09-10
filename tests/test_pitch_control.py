"""Pitch control, checked against situations with a known correct answer.

The strongest tests here are the symmetry ones: a mirror-image game state must produce
a mirror-image field, and one team's control must be exactly the complement of the
other's. Those catch the whole class of sign, axis-order, and row/column bugs that a
"does it look plausible" check misses.
"""

import numpy as np
import pytest

from soccersim.domain.entities import BallState, PlayerState, Team
from soccersim.domain.fixtures import counter_attack_snapshot, kickoff_433_vs_442
from soccersim.domain.pitch import Pitch, vec
from soccersim.domain.state import GameState, TeamState
from soccersim.space.grid import PitchGrid
from soccersim.space.pitch_control import DEFAULT_SHARPNESS, control_field


def build(home_players, away_players, ball=None) -> GameState:
    return GameState(
        pitch=Pitch(),
        home=TeamState(Team.HOME, home_players, 1),
        away=TeamState(Team.AWAY, away_players, -1),
        ball=BallState(ball if ball is not None else vec(0, 0)),
    )


GRID = PitchGrid(Pitch(), 4.0)


class TestGrid:
    @pytest.mark.parametrize("resolution", [1.5, 2.0, 3.0, 4.0])
    def test_extent_reproduces_the_pitch_exactly(self, resolution):
        """Cells are centred, so the extent must use realised steps, not the request."""
        grid = PitchGrid(Pitch(), resolution)
        xmin, xmax, ymin, ymax = grid.extent
        assert (xmin, xmax) == pytest.approx((-52.5, 52.5))
        assert (ymin, ymax) == pytest.approx((-34.0, 34.0))

    def test_cell_area_sums_to_pitch_area(self):
        grid = PitchGrid(Pitch(), 2.5)
        rows, cols = grid.shape
        assert rows * cols * grid.cell_area == pytest.approx(105.0 * 68.0)

    def test_points_are_row_major_and_inside_the_pitch(self):
        points = GRID.points()
        assert points.shape == (*GRID.shape, 2)
        assert np.all(Pitch().contains(points))

    def test_index_and_coord_round_trip(self):
        for point in (vec(0, 0), vec(-40, 20), vec(52.0, -33.0)):
            row, col = GRID.index_of(point)
            assert np.linalg.norm(GRID.coord_of(row, col) - point) <= GRID.resolution

    def test_rejects_non_positive_resolution(self):
        with pytest.raises(ValueError):
            PitchGrid(Pitch(), 0.0)


class TestDegenerateCases:
    def test_lone_team_owns_the_whole_pitch(self):
        state = build([PlayerState(1, Team.HOME, vec(0, 0))], [])
        field = control_field(state, Team.HOME, GRID)
        assert np.allclose(field.control, 1.0)

    def test_opponent_only_owns_nothing(self):
        state = build([], [PlayerState(21, Team.AWAY, vec(0, 0))])
        field = control_field(state, Team.HOME, GRID)
        assert np.allclose(field.control, 0.0)

    def test_empty_pitch_is_an_even_split(self):
        """Both arrival times infinite leaves the advantage undefined; call it even
        rather than propagating NaN into every consumer."""
        field = control_field(build([], []), Team.HOME, GRID)
        assert np.allclose(field.control, 0.5)
        assert not np.any(np.isnan(field.control))

    def test_unavailable_players_claim_no_space(self):
        state = build(
            [PlayerState(1, Team.HOME, vec(0, 0), available=False)],
            [PlayerState(21, Team.AWAY, vec(40, 0))],
        )
        field = control_field(state, Team.HOME, GRID)
        assert np.allclose(field.control, 0.0)


class TestSymmetry:
    def test_mirrored_teams_split_the_pitch_antisymmetrically(self):
        home = [PlayerState(i, Team.HOME, vec(-10 * i, 0)) for i in (1, 2, 3)]
        away = [PlayerState(20 + i, Team.AWAY, vec(10 * i, 0)) for i in (1, 2, 3)]
        field = control_field(build(home, away), Team.HOME, GRID)
        # Reflecting in x must invert control: what is mine there is theirs here.
        assert np.allclose(field.control, 1.0 - field.control[:, ::-1])

    def test_lateral_symmetry_for_a_lateral_symmetric_state(self):
        home = [PlayerState(1, Team.HOME, vec(-20, 0))]
        away = [PlayerState(21, Team.AWAY, vec(20, 0))]
        field = control_field(build(home, away), Team.HOME, GRID)
        assert np.allclose(field.control, field.control[::-1, :])

    def test_the_two_teams_views_are_complements(self):
        state = kickoff_433_vs_442()
        home_view = control_field(state, Team.HOME, GRID)
        away_view = control_field(state, Team.AWAY, GRID)
        assert np.allclose(home_view.control, 1.0 - away_view.control)

    def test_equal_arrival_time_gives_exactly_half(self):
        """A point both teams reach simultaneously is exactly even.

        The two players straddle an actual cell centre rather than the halfway line —
        no cell is centred on x = 0 — so this pins the model, not the grid's rounding.
        """
        centre = GRID.coord_of(*GRID.index_of(vec(0, 0)))
        home = [PlayerState(1, Team.HOME, centre - vec(20, 0))]
        away = [PlayerState(21, Team.AWAY, centre + vec(20, 0))]
        field = control_field(build(home, away), Team.HOME, GRID)
        assert field.at(centre) == pytest.approx(0.5)

    def test_the_even_contour_sits_on_the_halfway_line(self):
        """For a mirror-symmetric state the cells either side of x = 0 must bracket
        0.5 by exactly equal amounts."""
        home = [PlayerState(1, Team.HOME, vec(-20, 0))]
        away = [PlayerState(21, Team.AWAY, vec(20, 0))]
        field = control_field(build(home, away), Team.HOME, GRID)
        row = GRID.index_of(vec(0, 0))[0]
        left = int(np.searchsorted(GRID.xs, 0.0)) - 1
        assert GRID.xs[left] < 0.0 < GRID.xs[left + 1]
        below, above = field.control[row, left], field.control[row, left + 1]
        assert below > 0.5 > above
        assert below - 0.5 == pytest.approx(0.5 - above)


class TestMomentumMatters:
    def test_a_moving_player_beats_a_nearer_stationary_one(self):
        """The reason for using arrival time over distance (D-013): a sprinting player
        can own space a closer but stationary opponent cannot get to."""
        target = vec(30, 0)
        home = [PlayerState(1, Team.HOME, vec(0, 0), velocity=vec(8.0, 0.0))]
        away = [PlayerState(21, Team.AWAY, vec(8, 0), velocity=vec(-8.0, 0.0))]
        field = control_field(build(home, away), Team.HOME, PitchGrid(Pitch(), 2.0))
        assert field.at(target) > 0.5

    def test_a_distance_model_would_get_that_case_wrong(self):
        """Guard against a regression to a distance-based model: the away player is
        strictly nearer to the target, so distance alone would award it to them."""
        target = vec(30.0, 0.0)
        assert np.linalg.norm(target - vec(8, 0)) < np.linalg.norm(target - vec(0, 0))

    def test_control_shifts_ahead_of_a_sprinting_player(self):
        """Space is owned in front of momentum, not centred on the player's feet."""
        home = [PlayerState(1, Team.HOME, vec(0, 0), velocity=vec(8.0, 0.0))]
        away = [PlayerState(21, Team.AWAY, vec(0, 0), velocity=vec(-8.0, 0.0))]
        field = control_field(build(home, away), Team.HOME, PitchGrid(Pitch(), 2.0))
        assert field.at(vec(15, 0)) > field.at(vec(-15, 0))


class TestFieldAccessors:
    def test_advantage_is_the_arrival_time_difference(self):
        field = control_field(kickoff_433_vs_442(), Team.HOME, GRID)
        assert np.allclose(field.advantage, field.defence_time - field.attack_time)

    def test_higher_sharpness_makes_control_more_decisive(self):
        state = kickoff_433_vs_442()
        soft = control_field(state, Team.HOME, GRID, sharpness=0.2)
        hard = control_field(state, Team.HOME, GRID, sharpness=5.0)
        assert np.std(hard.control) > np.std(soft.control)

    def test_default_sharpness_reads_a_one_second_edge_as_dominance(self):
        """Documented calibration of the (uncalibrated, Q-005) sharpness constant."""
        assert 1.0 / (1.0 + np.exp(-DEFAULT_SHARPNESS * 1.0)) == pytest.approx(
            0.82, abs=0.01
        )

    def test_controlled_area_is_bounded_by_the_pitch(self):
        field = control_field(kickoff_433_vs_442(), Team.HOME, GRID)
        assert 0.0 < field.controlled_area() < 105.0 * 68.0

    def test_kickoff_shapes_split_the_pitch_roughly_evenly(self):
        field = control_field(kickoff_433_vs_442(), Team.HOME, GRID)
        share = field.controlled_area() / (105.0 * 68.0)
        assert 0.4 < share < 0.6

    def test_best_point_respects_a_mask(self):
        field = control_field(counter_attack_snapshot(), Team.HOME, GRID)
        points = field.grid.points()
        own_half_only = points[..., 0] < 0
        assert field.best_point(own_half_only)[0] < 0

    def test_control_is_bounded_to_the_unit_interval(self):
        field = control_field(counter_attack_snapshot(), Team.HOME, GRID)
        assert field.control.min() >= 0.0
        assert field.control.max() <= 1.0

    def test_resolution_does_not_change_the_answer_much(self):
        """Coarse grids are for speed, not for different physics."""
        state = counter_attack_snapshot()
        coarse = control_field(state, Team.HOME, PitchGrid(Pitch(), 5.0))
        fine = control_field(state, Team.HOME, PitchGrid(Pitch(), 1.5))
        assert coarse.control.mean() == pytest.approx(fine.control.mean(), abs=0.03)


class TestDirectionAgnostic:
    """Q-011: geometry expressed relative to ``attacking_direction`` should be
    unaffected by which way a team is playing. Cheap to check, easy to get subtly
    wrong, so it is checked rather than assumed."""

    @pytest.mark.parametrize("build_state", [kickoff_433_vs_442, counter_attack_snapshot])
    def test_mirroring_the_state_mirrors_the_control_field(self, build_state):
        from soccersim.domain.fixtures import mirrored

        original = control_field(build_state(), Team.HOME, GRID)
        flipped = control_field(mirrored(build_state()), Team.HOME, GRID)
        assert np.allclose(original.control, flipped.control[:, ::-1])

    def test_mirroring_preserves_controlled_area(self):
        from soccersim.domain.fixtures import mirrored

        state = counter_attack_snapshot()
        assert control_field(state, Team.HOME, GRID).controlled_area() == pytest.approx(
            control_field(mirrored(state), Team.HOME, GRID).controlled_area()
        )
