"""Hard constraints.

Offside gets the most attention because it is the one with a precise real-world
definition and three separate exemptions, each of which is easy to omit. Level counts
as onside in every case, which is where a naive implementation using ``>=`` goes wrong.
"""

import numpy as np
import pytest

from soccersim.domain.entities import (
    BallState,
    CapabilityProfile,
    PlayerState,
    Team,
    Waypoint,
)
from soccersim.domain.fixtures import wing_overload_snapshot
from soccersim.domain.pitch import Pitch, vec
from soccersim.domain.state import GameState, TeamState
from soccersim.constraints.feasibility import (
    Violation,
    check_in_bounds,
    check_offside,
    check_reachable,
    check_separation,
    check_waypoints,
    is_offside,
    reachability,
)

PITCH = Pitch()
# Back four at x = 40, 30, 25, 20 -> the second-last defender is at x = 30.
DEFENDERS = [(40.0, 0.0), (30.0, -5.0), (25.0, 5.0), (20.0, 10.0)]


class TestOffside:
    def test_beyond_the_second_last_defender_is_offside(self):
        assert is_offside(vec(35, 0), vec(0, 0), DEFENDERS, 1)

    def test_level_with_the_second_last_defender_is_onside(self):
        """Level is onside — the rule is 'beyond', not 'at or beyond'."""
        assert not is_offside(vec(30, 0), vec(0, 0), DEFENDERS, 1)

    def test_behind_the_defensive_line_is_onside(self):
        assert not is_offside(vec(20, 0), vec(0, 0), DEFENDERS, 1)

    def test_own_half_is_never_offside(self):
        assert not is_offside(vec(-5, 0), vec(-40, 0), [(-1.0, 0.0), (-2.0, 0.0)], 1)

    def test_on_the_halfway_line_is_onside(self):
        assert not is_offside(vec(0, 0), vec(-40, 0), [(-1.0, 0.0), (-2.0, 0.0)], 1)

    def test_level_with_the_ball_is_onside(self):
        assert not is_offside(vec(35, 0), vec(35, 10), DEFENDERS, 1)

    def test_behind_the_ball_is_onside(self):
        """Ahead of the defence but behind the ball — a squared pass back is legal."""
        assert not is_offside(vec(35, 0), vec(45, 0), DEFENDERS, 1)

    def test_mirrors_for_the_other_attacking_direction(self):
        mirrored = [(-x, y) for x, y in DEFENDERS]
        assert is_offside(vec(-35, 0), vec(0, 0), mirrored, -1)
        assert not is_offside(vec(-30, 0), vec(0, 0), mirrored, -1)

    def test_lateral_position_is_irrelevant(self):
        """Offside is judged on the attacking axis only."""
        for y in (-30.0, 0.0, 30.0):
            assert is_offside(vec(35, y), vec(0, 0), DEFENDERS, 1)

    def test_fewer_than_two_defenders_leaves_no_offside_line(self):
        assert is_offside(vec(35, 0), vec(0, 0), [(40.0, 0.0)], 1)

    def test_keeper_counts_toward_the_two_defenders(self):
        """With the keeper rushed upfield, the second-last defender can be an
        outfielder ahead of the ball — the rule counts players, not roles."""
        # Keeper at x = 10, one defender at x = 45: second-last is at x = 10.
        assert is_offside(vec(20, 0), vec(0, 0), [(45.0, 0.0), (10.0, 0.0)], 1)

    def test_wraps_into_a_violation_on_a_receiving_waypoint(self):
        state = wing_overload_snapshot()
        far_upfield = Waypoint(10, vec(49.0, 0.0), 2.0)
        found = check_offside(far_upfield, state, state.home)
        assert isinstance(found, Violation)
        assert found.constraint == "offside"

    def test_onside_waypoint_produces_no_violation(self):
        state = wing_overload_snapshot()
        assert check_offside(Waypoint(10, vec(20.0, 0.0), 2.0), state, state.home) is None


class TestReachability:
    PLAYER = PlayerState(
        1, Team.HOME, vec(0, 0), capability=CapabilityProfile(8.0, 8.0, 0.0)
    )

    def test_comfortable_waypoint_is_feasible_with_slack(self):
        result = reachability(self.PLAYER, Waypoint(1, vec(10, 0), 5.0))
        assert result.feasible
        assert result.slack > 0

    def test_impossible_waypoint_reports_the_shortfall(self):
        found = check_reachable(self.PLAYER, Waypoint(1, vec(60, 0), 1.0))
        assert found is not None
        assert found.constraint == "max_speed"
        assert "short by" in found.detail

    def test_slack_is_deadline_minus_arrival(self):
        result = reachability(self.PLAYER, Waypoint(1, vec(20, 0), 4.0))
        assert result.slack == pytest.approx(4.0 - result.arrival_time)

    def test_exactly_on_the_deadline_is_feasible(self):
        arrival = reachability(self.PLAYER, Waypoint(1, vec(20, 0), 99.0)).arrival_time
        assert reachability(self.PLAYER, Waypoint(1, vec(20, 0), arrival)).feasible

    def test_fatigue_can_make_a_waypoint_infeasible(self):
        """The same waypoint, the same player, different stamina (D-006)."""
        waypoint = Waypoint(1, vec(38.0, 0.0), 6.0)
        fresh = PlayerState(1, Team.HOME, vec(0, 0), stamina=1.0)
        tired = PlayerState(1, Team.HOME, vec(0, 0), stamina=0.0)
        assert check_reachable(fresh, waypoint) is None
        assert check_reachable(tired, waypoint) is not None

    def test_momentum_away_from_the_target_can_make_it_infeasible(self):
        waypoint = Waypoint(1, vec(38.0, 0.0), 6.0)
        still = PlayerState(1, Team.HOME, vec(0, 0))
        retreating = PlayerState(1, Team.HOME, vec(0, 0), velocity=vec(-7.0, 0.0))
        assert check_reachable(still, waypoint) is None
        assert check_reachable(retreating, waypoint) is not None


class TestBounds:
    def test_inside_is_fine(self):
        assert check_in_bounds(Waypoint(1, vec(0, 0), 1.0), PITCH) is None

    @pytest.mark.parametrize(
        "corner", [(52.5, 34.0), (-52.5, 34.0), (52.5, -34.0), (-52.5, -34.0)]
    )
    def test_exact_corners_are_in_play(self, corner):
        """Touchlines are part of the field of play."""
        assert check_in_bounds(Waypoint(1, vec(*corner), 1.0), PITCH) is None

    @pytest.mark.parametrize("point", [(53.0, 0.0), (0.0, 35.0), (-60.0, -40.0)])
    def test_outside_is_a_violation(self, point):
        found = check_in_bounds(Waypoint(1, vec(*point), 1.0), PITCH)
        assert found is not None
        assert found.constraint == "pitch_bounds"


class TestSeparation:
    def test_same_place_same_time_collides(self):
        found = check_separation(
            [Waypoint(1, vec(0, 0), 2.0), Waypoint(2, vec(0.4, 0.0), 2.0)]
        )
        assert found is not None
        assert found.constraint == "collision"

    def test_same_place_much_later_is_a_rotation_not_a_collision(self):
        assert (
            check_separation([Waypoint(1, vec(0, 0), 2.0), Waypoint(2, vec(0.4, 0.0), 9.0)])
            is None
        )

    def test_far_apart_at_the_same_time_is_fine(self):
        assert (
            check_separation([Waypoint(1, vec(0, 0), 2.0), Waypoint(2, vec(10, 0), 2.0)])
            is None
        )

    def test_a_player_does_not_collide_with_their_own_later_waypoint(self):
        assert (
            check_separation([Waypoint(1, vec(0, 0), 2.0), Waypoint(1, vec(0.1, 0.0), 2.0)])
            is None
        )

    def test_a_wider_buffer_catches_more(self):
        waypoints = [Waypoint(1, vec(0, 0), 2.0), Waypoint(2, vec(2.5, 0.0), 2.0)]
        assert check_separation(waypoints, min_separation=1.5) is None
        assert check_separation(waypoints, min_separation=4.0) is not None

    def test_empty_and_single_waypoint_sets_are_fine(self):
        assert check_separation([]) is None
        assert check_separation([Waypoint(1, vec(0, 0), 1.0)]) is None


class TestCheckWaypoints:
    def test_a_sane_play_passes_every_check(self):
        state = wing_overload_snapshot()
        waypoints = [
            Waypoint(5, vec(34.0, 30.0), 3.0, "overlap_run"),
            Waypoint(10, vec(42.0, 2.0), 3.0, "move_to"),
        ]
        assert check_waypoints(state, state.home, waypoints) == []

    def test_collects_every_violation_rather_than_short_circuiting(self):
        """When authoring a play by hand, seeing all the problems at once is more
        useful than being told about them one at a time."""
        state = wing_overload_snapshot()
        waypoints = [
            Waypoint(5, vec(80.0, 0.0), 1.0),  # out of bounds and unreachable
            Waypoint(10, vec(49.0, 0.0), 0.2),  # unreachable, and offside if receiving
        ]
        found = check_waypoints(state, state.home, waypoints, receiving_waypoints=(10,))
        constraints = [violation.constraint for violation in found]
        assert "pitch_bounds" in constraints
        assert "max_speed" in constraints
        assert "offside" in constraints

    def test_offside_only_applies_to_receiving_waypoints(self):
        state = wing_overload_snapshot()
        deep = [Waypoint(10, vec(49.0, 0.0), 20.0)]
        assert check_waypoints(state, state.home, deep) == []
        assert [
            violation.constraint
            for violation in check_waypoints(
                state, state.home, deep, receiving_waypoints=(10,)
            )
        ] == ["offside"]

    def test_unknown_player_is_an_eligibility_violation(self):
        state = wing_overload_snapshot()
        found = check_waypoints(state, state.home, [Waypoint(999, vec(0, 0), 5.0)])
        assert [violation.constraint for violation in found] == ["eligibility"]

    def test_unavailable_player_cannot_be_assigned(self):
        state = wing_overload_snapshot()
        state.home.players[5].available = False
        target = state.home.players[5]
        found = check_waypoints(state, state.home, [Waypoint(target.player_id, vec(15, 2), 5.0)])
        assert [violation.constraint for violation in found] == ["eligibility"]

    def test_violation_is_truthy_and_readable(self):
        violation = Violation("offside", "player 9 is beyond the line")
        assert violation
        assert str(violation) == "offside: player 9 is beyond the line"


class TestFixtureInvariants:
    """Guards on the hand-authored fixtures, so a later edit cannot silently make one
    physically absurd."""

    @pytest.mark.parametrize("name", ["kickoff", "wing_overload", "counter_attack"])
    def test_every_player_is_on_the_pitch_and_within_their_limits(self, name):
        from soccersim.domain.fixtures import ALL_FIXTURES

        state = ALL_FIXTURES[name]()
        assert len(state.home.players) == 11
        assert len(state.away.players) == 11
        for player in state.all_players():
            assert state.pitch.contains(player.position), player.player_id
            capability = player.effective_capability()
            assert player.speed <= capability.max_speed + 1e-9, player.player_id
            assert 0.0 <= player.stamina <= 1.0

    def test_player_ids_are_unique(self):
        from soccersim.domain.fixtures import ALL_FIXTURES

        for build in ALL_FIXTURES.values():
            state = build()
            ids = [player.player_id for player in state.all_players()]
            assert len(ids) == len(set(ids))

    def test_the_ball_is_where_its_carrier_is(self):
        from soccersim.domain.fixtures import ALL_FIXTURES

        for name, build in ALL_FIXTURES.items():
            state = build()
            if state.ball.carrier_id is not None:
                carrier = state.player(state.ball.carrier_id)
                gap = float(np.linalg.norm(carrier.position - state.ball.position))
                assert gap < 2.0, f"{name}: ball is {gap:.1f}m from its carrier"
