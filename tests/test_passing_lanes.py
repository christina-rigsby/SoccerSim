"""Passing-lane assessment and cover shadows.

The central property is monotonicity: as a defender is walked away from the line of a
pass, the pass must get monotonically safer. That is a stronger check than any single
open/closed verdict, because it constrains the whole shape of the model rather than one
point on it.
"""

import numpy as np
import pytest

from soccersim.domain.entities import BallState, PlayerState, Team
from soccersim.domain.fixtures import wing_overload_snapshot
from soccersim.domain.pitch import Pitch, vec
from soccersim.domain.state import GameState, TeamState
from soccersim.space.passing_lanes import (
    DEFAULT_PASS_SPEED,
    assess_lane,
    assess_lane_to_player,
    cover_shadow_polygon,
    in_cover_shadow,
    open_lanes,
)

PASSER = vec(-10.0, 0.0)
RECEIVER = vec(10.0, 0.0)


def build(defender_positions, receiver=RECEIVER) -> GameState:
    home = [
        PlayerState(1, Team.HOME, PASSER),
        PlayerState(2, Team.HOME, receiver),
    ]
    away = [
        PlayerState(20 + i, Team.AWAY, vec(*position))
        for i, position in enumerate(defender_positions)
    ]
    return GameState(
        pitch=Pitch(),
        home=TeamState(Team.HOME, home, 1),
        away=TeamState(Team.AWAY, away, -1),
        ball=BallState(PASSER),
    )


class TestBlocking:
    def test_defender_standing_on_the_line_blocks_it(self):
        lane = assess_lane(build([(0.0, 0.0)]), PASSER, RECEIVER, Team.HOME)
        assert not lane.is_open
        assert lane.blockers == (20,)
        assert lane.tightest_margin > 0

    def test_distant_defender_does_not_block(self):
        lane = assess_lane(build([(0.0, 20.0)]), PASSER, RECEIVER, Team.HOME)
        assert lane.is_open
        assert lane.blockers == ()

    def test_margin_is_monotone_in_lateral_offset(self):
        """Walking the defender off the line must make the pass monotonically safer."""
        margins = [
            assess_lane(build([(0.0, offset)]), PASSER, RECEIVER, Team.HOME).tightest_margin
            for offset in np.arange(0.0, 24.0, 2.0)
        ]
        assert all(later < earlier for earlier, later in zip(margins, margins[1:]))

    def test_no_defenders_means_a_free_lane(self):
        lane = assess_lane(build([]), PASSER, RECEIVER, Team.HOME)
        assert lane.is_open
        assert lane.tightest_margin == float("-inf")
        assert lane.blockers == ()

    def test_unavailable_defender_cannot_intercept(self):
        state = build([(0.0, 0.0)])
        state.away.players[0].available = False
        assert assess_lane(state, PASSER, RECEIVER, Team.HOME).is_open

    def test_a_faster_pass_is_harder_to_intercept(self):
        state = build([(0.0, 2.0)])
        slow = assess_lane(state, PASSER, RECEIVER, Team.HOME, pass_speed=6.0)
        fast = assess_lane(state, PASSER, RECEIVER, Team.HOME, pass_speed=30.0)
        assert fast.tightest_margin < slow.tightest_margin
        assert slow.is_open is False and fast.is_open is True

    def test_all_blockers_are_reported_not_just_the_closest(self):
        lane = assess_lane(build([(-2.0, 0.0), (4.0, 0.3)]), PASSER, RECEIVER, Team.HOME)
        assert set(lane.blockers) == {20, 21}

    def test_tightest_point_lies_on_the_lane(self):
        lane = assess_lane(build([(3.0, 1.0)]), PASSER, RECEIVER, Team.HOME)
        span = RECEIVER - PASSER
        offset = lane.tightest_point - PASSER
        cross = float(span[0] * offset[1] - span[1] * offset[0])
        assert cross == pytest.approx(0.0, abs=1e-9)
        assert 0.0 <= float(offset @ span) / float(span @ span) <= 1.0

    def test_momentum_toward_the_lane_helps_the_defender(self):
        static = assess_lane(build([(0.0, 6.0)]), PASSER, RECEIVER, Team.HOME)
        state = build([(0.0, 6.0)])
        state.away.players[0].velocity = vec(0.0, -8.0)  # sprinting onto the lane
        moving = assess_lane(state, PASSER, RECEIVER, Team.HOME)
        assert moving.tightest_margin > static.tightest_margin

    def test_safety_margin_makes_the_test_stricter(self):
        state = build([(0.0, 3.0)])
        assert assess_lane(state, PASSER, RECEIVER, Team.HOME).is_open
        strict = assess_lane(state, PASSER, RECEIVER, Team.HOME, safety_margin=-2.0)
        assert not strict.is_open

    def test_lane_length_is_reported(self):
        lane = assess_lane(build([]), PASSER, RECEIVER, Team.HOME)
        assert lane.length == pytest.approx(20.0)

    def test_very_short_lane_does_not_crash(self):
        """Below the minimum sample distance there is nothing to occlude."""
        lane = assess_lane(build([(0.0, 0.0)]), PASSER, PASSER + vec(0.3, 0.0), Team.HOME)
        assert lane.length == pytest.approx(0.3)


class TestLaneHelpers:
    def test_assess_to_player_uses_their_position(self):
        state = build([])
        receiver = state.home.players[1]
        lane = assess_lane_to_player(state, PASSER, receiver)
        assert np.allclose(lane.target, receiver.position)

    def test_open_lanes_covers_every_teammate_and_sorts_by_margin(self):
        state = wing_overload_snapshot()
        lanes = open_lanes(state, state.ball.position, Team.HOME, exclude=(11,))
        assert len(lanes) == len(state.home.available()) - 1
        margins = [assessment.tightest_margin for _, assessment in lanes]
        assert margins == sorted(margins)

    def test_open_lanes_can_exclude_the_carrier(self):
        state = wing_overload_snapshot()
        lanes = open_lanes(state, state.ball.position, Team.HOME, exclude=(11,))
        assert 11 not in {player.player_id for player, _ in lanes}

    def test_default_pass_speed_is_a_plausible_ground_pass(self):
        assert 8.0 < DEFAULT_PASS_SPEED < 30.0


class TestCoverShadow:
    BALL = vec(-10.0, 0.0)
    DEFENDER = vec(0.0, 0.0)

    def test_directly_behind_the_defender_is_shadowed(self):
        assert in_cover_shadow(vec(20, 0), self.BALL, self.DEFENDER)

    def test_in_front_of_the_defender_is_not_shadowed(self):
        assert not in_cover_shadow(vec(-5, 0), self.BALL, self.DEFENDER)

    def test_off_axis_is_not_shadowed(self):
        assert not in_cover_shadow(vec(20, 5), self.BALL, self.DEFENDER)

    def test_the_shadow_widens_with_range(self):
        """The wedge diverges, so a point twice as far tolerates twice the offset."""
        near_limit = 0.0
        far_limit = 0.0
        for offset in np.arange(0.0, 3.0, 0.05):
            if in_cover_shadow(vec(10.0, offset), self.BALL, self.DEFENDER):
                near_limit = offset
            if in_cover_shadow(vec(40.0, offset), self.BALL, self.DEFENDER):
                far_limit = offset
        assert far_limit > near_limit

    def test_shadow_rotates_with_the_ball(self):
        """Move the ball and the shadow must swing round behind the defender."""
        assert in_cover_shadow(vec(0, 20), vec(0, -10), self.DEFENDER)
        assert not in_cover_shadow(vec(20, 0), vec(0, -10), self.DEFENDER)

    def test_vectorises_over_points(self):
        points = np.array([[20.0, 0.0], [-5.0, 0.0], [20.0, 5.0]])
        result = in_cover_shadow(points, self.BALL, self.DEFENDER)
        assert result.tolist() == [True, False, False]

    def test_defender_on_the_ball_shadows_nothing(self):
        assert not in_cover_shadow(vec(20, 0), self.BALL, self.BALL)

    def test_polygon_starts_at_the_defender_and_points_away(self):
        polygon = cover_shadow_polygon(self.BALL, self.DEFENDER, depth=30.0)
        assert polygon.shape == (3, 2)
        assert np.allclose(polygon[0], self.DEFENDER)
        # The far edge sits `depth` beyond the defender, along the ball -> defender axis.
        assert polygon[1][0] == pytest.approx(30.0)
        assert polygon[2][0] == pytest.approx(30.0)

    def test_polygon_is_degenerate_when_defender_is_on_the_ball(self):
        polygon = cover_shadow_polygon(self.BALL, self.BALL)
        assert np.allclose(polygon, self.BALL)
