"""Arrival-time model, checked against closed-form values.

``time_to_point`` is called by both the pitch-control field and the ``max_speed`` hard
constraint, so an error here biases everything downstream in the same direction. These
tests pin it to hand-computed answers rather than to its own previous output.
"""

import numpy as np
import pytest

from soccersim.domain.entities import CapabilityProfile, PlayerState, Team
from soccersim.domain.pitch import vec
from soccersim.kinematics import (
    best_time_to_point,
    player_time_to_point,
    team_time_to_point,
    time_to_point,
    travel_time,
)

# Round numbers so the closed forms stay legible.
PROFILE = CapabilityProfile(max_speed=8.0, max_accel=8.0, reaction_time=0.0)


class TestTravelTime:
    def test_triangular_branch_from_rest(self):
        """Too short to reach top speed: d = a t^2 / 2, so t = sqrt(2d/a)."""
        # accel_distance = 8^2 / (2*8) = 4 m, so 1 m takes the triangular branch.
        assert travel_time(1.0, 0.0, 8.0, 8.0) == pytest.approx(np.sqrt(2 * 1.0 / 8.0))

    def test_trapezoidal_branch_from_rest(self):
        """Long enough to cruise: accelerate 4 m in 1 s, then 46 m at 8 m/s."""
        assert travel_time(50.0, 0.0, 8.0, 8.0) == pytest.approx(1.0 + 46.0 / 8.0)

    def test_already_at_top_speed_is_pure_cruise(self):
        assert travel_time(40.0, 8.0, 8.0, 8.0) == pytest.approx(40.0 / 8.0)

    def test_boundary_between_branches_is_continuous(self):
        """The two branches must agree exactly at accel_distance."""
        accel_distance = 8.0**2 / (2 * 8.0)
        below = travel_time(accel_distance - 1e-7, 0.0, 8.0, 8.0)
        above = travel_time(accel_distance + 1e-7, 0.0, 8.0, 8.0)
        assert below == pytest.approx(above, abs=1e-5)

    def test_zero_distance_is_zero_time(self):
        assert travel_time(0.0, 0.0, 8.0, 8.0) == pytest.approx(0.0)

    def test_monotone_in_distance(self):
        times = travel_time(np.arange(0.0, 100.0, 2.5), 0.0, 8.0, 8.0)
        assert np.all(np.diff(times) > 0)

    def test_initial_speed_is_clipped_not_rejected(self):
        """A speed above max_speed is treated as max_speed, not as an error."""
        assert travel_time(40.0, 99.0, 8.0, 8.0) == pytest.approx(40.0 / 8.0)

    def test_vectorises_over_distance(self):
        out = travel_time(np.array([1.0, 50.0]), 0.0, 8.0, 8.0)
        assert out.shape == (2,)
        assert out[0] == pytest.approx(np.sqrt(2 / 8.0))

    @pytest.mark.parametrize("bad", [dict(max_speed=0.0), dict(max_accel=-1.0)])
    def test_rejects_non_positive_limits(self, bad):
        kwargs = dict(max_speed=8.0, max_accel=8.0) | bad
        with pytest.raises(ValueError):
            travel_time(10.0, 0.0, **kwargs)


class TestTimeToPoint:
    def test_stationary_matches_travel_time_plus_reaction(self):
        profile = CapabilityProfile(max_speed=8.0, max_accel=8.0, reaction_time=0.3)
        expected = 0.3 + travel_time(40.0, 0.0, 8.0, 8.0)
        assert time_to_point(vec(0, 0), vec(0, 0), profile, vec(40, 0)) == pytest.approx(
            expected
        )

    def test_momentum_toward_target_is_fastest(self):
        toward = time_to_point(vec(0, 0), vec(8, 0), PROFILE, vec(40, 0))
        still = time_to_point(vec(0, 0), vec(0, 0), PROFILE, vec(40, 0))
        away = time_to_point(vec(0, 0), vec(-8, 0), PROFILE, vec(40, 0))
        assert toward < still < away

    def test_momentum_away_pays_to_arrest_velocity(self):
        """Reversing costs |v| / a on top of starting from rest."""
        still = time_to_point(vec(0, 0), vec(0, 0), PROFILE, vec(40, 0))
        away = time_to_point(vec(0, 0), vec(-8, 0), PROFILE, vec(40, 0))
        assert away - still == pytest.approx(8.0 / 8.0)

    def test_perpendicular_momentum_costs_the_same_as_reversing(self):
        """The model charges for the magnitude of the velocity change, so |v| is what
        matters, not its sign relative to the target."""
        perpendicular = time_to_point(vec(0, 0), vec(0, 8), PROFILE, vec(40, 0))
        reversed_ = time_to_point(vec(0, 0), vec(-8, 0), PROFILE, vec(40, 0))
        assert perpendicular == pytest.approx(reversed_)

    def test_standing_on_the_target_costs_only_reaction_time(self):
        profile = CapabilityProfile(max_speed=8.0, max_accel=8.0, reaction_time=0.25)
        assert time_to_point(vec(5, 5), vec(3, 3), profile, vec(5, 5)) == pytest.approx(
            0.25
        )

    def test_direction_agnostic(self):
        """Mirroring the whole problem must not change the answer."""
        forward = time_to_point(vec(0, 0), vec(2, 1), PROFILE, vec(30, 10))
        mirrored = time_to_point(vec(0, 0), vec(-2, 1), PROFILE, vec(-30, 10))
        assert forward == pytest.approx(mirrored)

    def test_shape_follows_targets(self):
        targets = np.zeros((4, 7, 2))
        assert np.asarray(
            time_to_point(vec(0, 0), vec(0, 0), PROFILE, targets)
        ).shape == (4, 7)

    def test_grid_evaluation_matches_pointwise(self):
        targets = np.array([[[1.0, 0.0], [10.0, 0.0]], [[20.0, 5.0], [40.0, -5.0]]])
        grid = np.asarray(time_to_point(vec(0, 0), vec(3, 1), PROFILE, targets))
        for row in range(2):
            for col in range(2):
                point = time_to_point(vec(0, 0), vec(3, 1), PROFILE, targets[row, col])
                assert grid[row, col] == pytest.approx(float(point))


class TestPlayerAndTeamHelpers:
    def test_fatigue_slows_a_player(self):
        fresh = PlayerState(1, Team.HOME, vec(0, 0), stamina=1.0)
        tired = PlayerState(2, Team.HOME, vec(0, 0), stamina=0.0)
        assert player_time_to_point(tired, vec(40, 0)) > player_time_to_point(
            fresh, vec(40, 0)
        )

    def test_team_times_stack_per_player(self):
        players = [
            PlayerState(1, Team.HOME, vec(0, 0)),
            PlayerState(2, Team.HOME, vec(10, 0)),
        ]
        times = team_time_to_point(players, np.zeros((3, 2)))
        assert times.shape == (2, 3)

    def test_empty_team_has_no_leading_axis(self):
        times = team_time_to_point([], np.zeros((3, 2)))
        assert times.shape == (0, 3)

    def test_best_time_picks_the_nearest_player(self):
        players = [
            PlayerState(1, Team.HOME, vec(0, 0)),
            PlayerState(2, Team.HOME, vec(35, 0)),
        ]
        assert float(best_time_to_point(players, vec(40, 0))) == pytest.approx(
            float(player_time_to_point(players[1], vec(40, 0)))
        )

    def test_empty_team_never_arrives(self):
        """An empty team has no claim on any point, rather than an instant one."""
        assert np.isinf(best_time_to_point([], vec(0, 0)))
