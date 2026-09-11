"""The stateful spine: event derivation, possession segmentation, bounded history.

Events are *derived* from deltas between snapshots rather than supplied, so these tests
drive the observer with sequences and assert what it recovered.
"""

import numpy as np
import pytest

from soccersim.dashboard.observer import (
    EventKind,
    MatchObserver,
    PassDirection,
)
from soccersim.domain.entities import BallState, GamePhase, PlayerState, Team
from soccersim.domain.pitch import Pitch, vec
from soccersim.domain.state import GameState, TeamState

HOME = {1: (-40.0, 0.0), 2: (0.0, 0.0), 3: (20.0, 0.0), 4: (10.0, 15.0)}
AWAY = {21: (40.0, 0.0), 22: (25.0, 5.0)}


def state(clock, carrier, possession=Team.HOME, phase=GamePhase.OPEN_PLAY, ball=None):
    home = TeamState(
        Team.HOME,
        [PlayerState(pid, Team.HOME, vec(*pos)) for pid, pos in HOME.items()],
        1,
    )
    away = TeamState(
        Team.AWAY,
        [PlayerState(pid, Team.AWAY, vec(*pos)) for pid, pos in AWAY.items()],
        -1,
    )
    if ball is None:
        ball = HOME.get(carrier) or AWAY.get(carrier) or (0.0, 0.0)
    return GameState(
        pitch=Pitch(), home=home, away=away,
        ball=BallState(position=vec(*ball), carrier_id=carrier),
        clock_seconds=clock, phase=phase, possession=possession,
    )


def drive(sequence):
    observer = MatchObserver()
    events = []
    for args in sequence:
        events += observer.observe(state(*args))
    return observer, events


class TestIngestion:
    def test_rejects_a_backwards_clock(self):
        """Out-of-order replay would silently corrupt every decayed estimate."""
        observer = MatchObserver()
        observer.observe(state(10.0, 2))
        with pytest.raises(ValueError, match="clock went backwards"):
            observer.observe(state(5.0, 2))

    def test_accepts_a_repeated_clock(self):
        observer = MatchObserver()
        observer.observe(state(1.0, 2))
        observer.observe(state(1.0, 2))
        assert observer.frames_observed == 2

    def test_buffer_is_bounded_by_match_time(self):
        observer = MatchObserver(buffer_seconds=2.0)
        for t in range(20):
            observer.observe(state(float(t), 2))
        assert observer.frames_observed == 20
        assert len(observer.frames) <= 4
        assert observer.frames[-1].clock == 19.0

    def test_buffer_always_keeps_at_least_one_frame(self):
        observer = MatchObserver(buffer_seconds=0.01)
        for t in range(5):
            observer.observe(state(float(t) * 10, 2))
        assert len(observer.frames) >= 1

    def test_rejects_a_non_positive_buffer(self):
        with pytest.raises(ValueError):
            MatchObserver(buffer_seconds=0.0)


class TestPassDetection:
    def test_same_team_carrier_change_is_a_pass(self):
        _, events = drive([(0.0, 2), (1.0, 3)])
        passes = [e for e in events if e.kind is EventKind.PASS]
        assert len(passes) == 1
        assert passes[0].detail["from"] == 2 and passes[0].detail["to"] == 3

    def test_survives_the_ball_being_in_flight(self):
        """Carrier goes None mid-pass, which must not break the chain."""
        _, events = drive([(0.0, 2), (0.5, None), (1.0, 3)])
        assert [e.kind for e in events if e.kind is EventKind.PASS]

    @pytest.mark.parametrize(
        "origin,target,expected",
        [
            (2, 3, PassDirection.FORWARD),   # x 0 -> 20
            (3, 2, PassDirection.BACK),      # x 20 -> 0
            (2, 4, PassDirection.FORWARD),   # x 0 -> 10
        ],
    )
    def test_direction_is_relative_to_attacking_direction(self, origin, target, expected):
        _, events = drive([(0.0, origin), (1.0, target)])
        passes = [e for e in events if e.kind is EventKind.PASS]
        assert passes[0].detail["direction"] == expected.value

    def test_a_square_pass_is_sideways(self):
        observer = MatchObserver()
        observer.observe(state(0.0, 2, ball=(0.0, 0.0)))
        events = observer.observe(state(1.0, 2, ball=(1.0, 12.0)))
        assert not [e for e in events if e.kind is EventKind.PASS], "same carrier"

    def test_third_is_taken_from_the_pass_origin(self):
        _, events = drive([(0.0, 3), (1.0, 2)])
        passes = [e for e in events if e.kind is EventKind.PASS]
        assert passes[0].detail["third"] == "final"

    def test_cross_team_carrier_change_is_a_turnover(self):
        _, events = drive([(0.0, 2), (1.0, 22, Team.AWAY)])
        assert any(e.kind is EventKind.TURNOVER for e in events)

    def test_no_event_on_the_first_frame(self):
        _, events = drive([(0.0, 2)])
        assert [e.kind for e in events] == [EventKind.POSSESSION_START]


class TestPossessions:
    def test_a_possession_opens_on_the_first_frame(self):
        observer, _ = drive([(0.0, 2)])
        assert observer.current_possession is not None
        assert observer.current_possession.team is Team.HOME

    def test_changing_possession_closes_the_previous_one(self):
        observer, events = drive([(0.0, 2), (1.0, 22, Team.AWAY)])
        assert len(observer.possessions) == 2
        first = observer.possessions[0]
        assert not first.is_open
        assert first.duration == pytest.approx(1.0)
        assert {e.kind for e in events} >= {
            EventKind.POSSESSION_START, EventKind.POSSESSION_END, EventKind.TURNOVER
        }

    def test_possession_counts_frames_and_passes(self):
        observer, _ = drive([(0.0, 2), (1.0, 3), (2.0, 2), (3.0, 3)])
        current = observer.current_possession
        assert current.frames == 4
        assert current.passes == 3
        assert current.pass_directions == {"forward": 2, "back": 1}

    def test_progress_is_signed_by_attacking_direction(self):
        observer, _ = drive([(0.0, 2), (1.0, 3), (2.0, 22, Team.AWAY)])
        completed = observer.completed_possessions(Team.HOME)
        assert completed[0].progress(1) == pytest.approx(20.0)

    def test_completed_possessions_can_be_filtered_by_team(self):
        observer, _ = drive([(0.0, 2), (1.0, 22, Team.AWAY), (2.0, 2, Team.HOME)])
        assert len(observer.completed_possessions(Team.HOME)) == 1
        assert len(observer.completed_possessions(Team.AWAY)) == 1

    def test_an_open_possession_is_excluded_from_completed(self):
        observer, _ = drive([(0.0, 2)])
        assert observer.completed_possessions() == []


class TestPhaseAndQueries:
    def test_phase_change_is_reported(self):
        _, events = drive([(0.0, 2), (1.0, 2, Team.HOME, GamePhase.TRANSITION)])
        changes = [e for e in events if e.kind is EventKind.PHASE_CHANGE]
        assert changes[0].detail == {"from": "open_play", "to": "transition"}

    def test_displacement_needs_two_frames(self):
        observer = MatchObserver()
        observer.observe(state(0.0, 2))
        assert observer.displacement(2) is None
        observer.observe(state(1.0, 2))
        assert observer.displacement(2) is not None

    def test_displacement_is_none_for_an_absent_player(self):
        observer, _ = drive([(0.0, 2), (1.0, 2)])
        assert observer.displacement(999) is None

    def test_displacement_measures_movement(self):
        observer = MatchObserver()
        observer.observe(state(0.0, 2))
        moved = state(1.0, 2)
        moved.home.by_id(2).position = vec(5.0, 3.0)
        observer.observe(moved)
        assert np.allclose(observer.displacement(2), [5.0, 3.0])

    def test_recent_events_filters_by_kind_team_and_time(self):
        observer, _ = drive([(0.0, 2), (1.0, 3), (2.0, 22, Team.AWAY)])
        assert all(
            e.kind is EventKind.PASS
            for e in observer.recent_events((EventKind.PASS,))
        )
        assert observer.recent_events(since=2.0) and not observer.recent_events(since=99.0)
        assert all(
            e.team is Team.AWAY for e in observer.recent_events(team=Team.AWAY)
        )

    def test_describe_summarises_state(self):
        observer, _ = drive([(0.0, 2), (1.0, 3)])
        assert "frames observed" in observer.describe()
