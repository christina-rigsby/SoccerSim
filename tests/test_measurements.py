"""Single-frame measurements.

These are facts about one snapshot, so they are tested against hand-constructed states
with known geometry rather than against accumulated behaviour.
"""

import numpy as np
import pytest

from soccersim.dashboard.measurements import (
    PRESSURE_HORIZON,
    BlockType,
    block_height,
    block_type,
    defensive_line,
    outfield,
    pressure_on,
    pressure_on_ball,
    situation_key,
    team_shape,
    zone_occupancy,
)
from soccersim.domain.entities import BallState, PlayerState, PositionalRole, Team
from soccersim.domain.fixtures import ALL_FIXTURES, counter_attack_snapshot, wing_overload_snapshot
from soccersim.domain.pitch import Pitch, vec
from soccersim.domain.state import GameState, TeamState


def team(positions, direction=1, team_id=Team.HOME, slots=None):
    slots = slots or {}
    players = [
        PlayerState(
            player_id=pid,
            team=team_id,
            position=vec(*pos),
            positional_role=slots.get(pid, PositionalRole.CB),
        )
        for pid, pos in positions.items()
    ]
    return TeamState(team_id, players, direction)


class TestOutfield:
    def test_excludes_the_goalkeeper(self):
        state = team({1: (-50, 0), 2: (-30, 0)}, slots={1: PositionalRole.GK})
        assert [p.player_id for p in outfield(state)] == [2]

    def test_excludes_unavailable_players(self):
        state = team({2: (-30, 0), 3: (-30, 5)})
        state.players[0].available = False
        assert [p.player_id for p in outfield(state)] == [3]

    def test_keeper_exclusion_changes_block_height(self):
        """The keeper is always deepest, so including them drags depth goalward."""
        with_keeper = team({1: (-50, 0), 2: (0, 0)}, slots={1: PositionalRole.GK})
        assert block_height(with_keeper) == pytest.approx(0.0)


class TestDefensiveLine:
    def test_picks_the_deepest_outfielders(self):
        state = team({2: (-40, -20), 3: (-40, -7), 4: (-40, 7), 5: (-40, 20), 6: (0, 0)})
        line = defensive_line(state, count=4)
        assert set(line.player_ids) == {2, 3, 4, 5}
        assert line.height == pytest.approx(-40.0)

    def test_orders_members_left_to_right(self):
        state = team({2: (-40, 20), 3: (-40, -20), 4: (-40, 0)})
        assert defensive_line(state, count=3).player_ids == (3, 4, 2)

    def test_gaps_and_widest_pair(self):
        """§3's 'midpoint of the gap between CB and fullback' waypoint needs this."""
        state = team({2: (-40, -20), 3: (-40, -5), 4: (-40, 5), 5: (-40, 20)})
        line = defensive_line(state, count=4)
        assert line.gaps == pytest.approx((15.0, 10.0, 15.0))
        assert line.largest_gap == pytest.approx(15.0)
        assert line.largest_gap_between in {(2, 3), (5, 4), (4, 5)}

    def test_tilt_measures_line_stagger(self):
        flat = team({2: (-40, -10), 3: (-40, 10)})
        tilted = team({2: (-40, -10), 3: (-28, 10)})
        assert defensive_line(flat, 2).tilt == pytest.approx(0.0)
        assert defensive_line(tilted, 2).tilt == pytest.approx(12.0)

    def test_direction_relative(self):
        """Mirroring the team and its direction must give the same line height."""
        forward = team({2: (-40, 0), 3: (-40, 10)}, direction=1)
        mirrored = team({2: (40, 0), 3: (40, 10)}, direction=-1)
        assert defensive_line(forward, 2).height == pytest.approx(
            defensive_line(mirrored, 2).height
        )

    def test_too_few_players_has_no_line(self):
        assert defensive_line(team({2: (-40, 0)})) is None


class TestBlockType:
    @pytest.mark.parametrize(
        "x,expected",
        [(-48.0, BlockType.LOW), (-25.0, BlockType.MID), (5.0, BlockType.HIGH)],
    )
    def test_classifies_by_line_height(self, x, expected):
        state = team({2: (x, -10), 3: (x, 0), 4: (x, 10)})
        assert block_type(state, Pitch()) is expected

    def test_a_line_past_halfway_is_high(self):
        state = team({2: (20, -10), 3: (20, 10)})
        assert block_type(state, Pitch()) is BlockType.HIGH

    def test_mirrors_across_attacking_direction(self):
        forward = team({2: (-48, -10), 3: (-48, 10)}, direction=1)
        mirrored = team({2: (48, -10), 3: (48, 10)}, direction=-1)
        assert block_type(forward, Pitch()) is block_type(mirrored, Pitch())

    def test_no_line_means_no_classification(self):
        assert block_type(team({2: (0, 0)}), Pitch()) is None


def two_team_state(home_positions, away_positions, ball_carrier=None, ball=None, **kw):
    home = team(home_positions, 1, Team.HOME)
    away = team(away_positions, -1, Team.AWAY, slots={})
    ball_position = ball if ball is not None else (
        home.by_id(ball_carrier).position if ball_carrier else vec(0, 0)
    )
    return GameState(
        pitch=Pitch(), home=home, away=away,
        ball=BallState(position=np.asarray(ball_position, dtype=float), carrier_id=ball_carrier),
        possession=Team.HOME if ball_carrier else None, **kw,
    )


class TestPressure:
    def test_nobody_near_means_no_pressure(self):
        state = two_team_state({1: (0, 0)}, {21: (50, 30)}, ball_carrier=1)
        pressure = pressure_on(state, 1)
        assert pressure.count == 0
        assert pressure.intensity == 0.0
        assert not pressure.is_pressed

    def test_a_close_opponent_applies_pressure(self):
        state = two_team_state({1: (0, 0)}, {21: (3, 0)}, ball_carrier=1)
        pressure = pressure_on(state, 1)
        assert pressure.pressing_ids == (21,)
        assert pressure.is_pressed
        assert pressure.intensity > 0

    def test_more_opponents_means_more_intensity(self):
        one = pressure_on(two_team_state({1: (0, 0)}, {21: (3, 0)}, ball_carrier=1), 1)
        three = pressure_on(
            two_team_state({1: (0, 0)}, {21: (3, 0), 22: (0, 3), 23: (-3, 0)}, ball_carrier=1), 1
        )
        assert three.intensity > one.intensity

    def test_distant_opponents_contribute_nothing_however_fast_they_move(self):
        """The bug this guards: summing closing speed over everyone inside the radius
        let defenders merely drifting back past the ball register as a press, and that
        phantom press was then credited to whichever pass preceded it."""
        state = two_team_state({1: (0, 0)}, {21: (16, 0)}, ball_carrier=1)
        state.away.players[0].velocity = vec(-9.0, 0.0)  # sprinting at the carrier
        pressure = pressure_on(state, 1)
        assert pressure.nearest_arrival > PRESSURE_HORIZON
        assert pressure.pressing_ids == ()
        assert pressure.intensity == 0.0

    def test_closing_opponents_press_harder_than_standing_ones(self):
        standing = two_team_state({1: (0, 0)}, {21: (4, 0)}, ball_carrier=1)
        closing = two_team_state({1: (0, 0)}, {21: (4, 0)}, ball_carrier=1)
        closing.away.players[0].velocity = vec(-6.0, 0.0)
        assert pressure_on(closing, 1).intensity > pressure_on(standing, 1).intensity

    def test_works_for_any_player_not_just_the_carrier(self):
        """So it also answers 'would this receiver be under pressure'."""
        state = two_team_state({1: (0, 0), 2: (20, 0)}, {21: (21, 0)}, ball_carrier=1)
        assert pressure_on(state, 2).is_pressed

    def test_unavailable_opponents_apply_no_pressure(self):
        state = two_team_state({1: (0, 0)}, {21: (2, 0)}, ball_carrier=1)
        state.away.players[0].available = False
        assert pressure_on(state, 1).count == 0

    def test_pressure_on_ball_is_none_without_a_carrier(self):
        assert pressure_on_ball(two_team_state({1: (0, 0)}, {21: (2, 0)})) is None


class TestZonesAndSituation:
    def test_zone_occupancy_counts_outfielders_by_cell(self):
        state = team(
            {1: (-50, 0), 2: (-40, -25), 3: (-40, -24)},
            slots={1: PositionalRole.GK},
        )
        counts = zone_occupancy(state, Pitch())
        assert sum(counts.values()) == 2
        assert counts[("defensive", "left")] == 2

    def test_situation_key_has_three_coarse_parts(self):
        key = situation_key(wing_overload_snapshot(), Team.HOME)
        assert key == ("final", "low", "open_play")

    def test_situation_key_changes_with_ball_zone(self):
        assert situation_key(counter_attack_snapshot(), Team.HOME)[0] == "middle"


class TestTeamShape:
    @pytest.mark.parametrize("name", sorted(ALL_FIXTURES))
    def test_composes_for_every_fixture(self, name):
        state = ALL_FIXTURES[name]()
        for side in (state.home, state.away):
            shape = team_shape(side, state.pitch)
            assert shape.players_available == 11
            assert shape.width > 0 and shape.depth > 0
            assert shape.line is not None
            assert shape.describe()

    def test_reuses_the_existing_team_state_helpers(self):
        """Shape metrics already existed on TeamState; this must not fork them."""
        state = wing_overload_snapshot()
        shape = team_shape(state.home, state.pitch)
        existing = state.home.shape()
        assert shape.width == existing["width"]
        assert shape.depth == existing["depth"]
        assert shape.compactness == existing["compactness"]
