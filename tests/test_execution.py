"""Running plays forward — the part that actually fires the triggers.

Instantiation can be tested on a snapshot; triggers cannot, because nothing fires unless
the world changes. These tests drive plays through the rehearsal harness and assert on
the lifecycle: steps activate in dependency order, complete by the right rule, abort when
told to, and time out rather than hanging.
"""

import numpy as np
import pytest

from soccersim.domain.entities import Team
from soccersim.domain.fixtures import opponent_buildup_snapshot, wing_overload_snapshot
from soccersim.plays import PlayExecution, PlayState, StepState, load_library
from soccersim.plays.anchors import anchor_from_spec
from soccersim.plays.triggers import trigger_from_spec
from soccersim.plays.play import Play, PlayStep
from soccersim.plays.rehearsal import rehearse

OVERLAP = {"wide_creator": 11, "overlap_runner": 5, "box_target": 10, "runner_in_behind": 9}
UNDERLAP = {"wide_creator": 11, "underlap_runner": 5, "deep_lying_passer": 6, "box_target": 10}


def with_ball(state, player_id):
    state.ball.carrier_id = player_id
    state.ball.position = np.array(state.player(player_id).position, dtype=float)
    return state


def step(key, role="wide_creator", action="move_to", anchor=None, **kwargs):
    for field in ("trigger", "completes_when", "abort_if"):
        if field in kwargs and isinstance(kwargs[field], dict):
            kwargs[field] = trigger_from_spec(kwargs[field])
    return PlayStep(
        key=key, role=role, action=action,
        anchor=anchor_from_spec(anchor) if anchor is not None else None,
        **kwargs,
    )


def make_play(steps, **kwargs):
    defaults = dict(key="t", label="T", description="d", objective="score", strategy="s")
    return Play(steps=tuple(steps), **{**defaults, **kwargs})


class TestLifecycle:
    def test_a_play_runs_to_completion(self):
        play = load_library().get("overlap_right")
        state = with_ball(wing_overload_snapshot(), 11)
        result = rehearse(play, state, OVERLAP, Team.HOME, max_seconds=30.0)
        assert result.completed, result.describe()
        assert len(result.execution.completed_steps) == len(play.steps)

    def test_a_second_play_also_completes(self):
        play = load_library().get("underlap_right")
        state = with_ball(wing_overload_snapshot(), 6)
        result = rehearse(play, state, UNDERLAP, Team.HOME, max_seconds=35.0)
        assert result.completed, result.describe()

    def test_a_press_play_completes_out_of_possession(self):
        from soccersim.plays import greedy_assignment

        play = load_library().get("trigger_press")
        state = opponent_buildup_snapshot()
        assignment = greedy_assignment(play, state, Team.HOME).assignment
        result = rehearse(play, state, assignment, Team.HOME, max_seconds=20.0)
        assert result.completed, result.describe()

    def test_steps_activate_in_dependency_order(self):
        play = load_library().get("overlap_right")
        state = with_ball(wing_overload_snapshot(), 11)
        result = rehearse(play, state, OVERLAP, Team.HOME, max_seconds=30.0)
        progress = result.execution.progress
        assert progress["release"].activated_at >= progress["carry"].activated_at
        assert progress["cross"].activated_at >= progress["release"].activated_at
        assert progress["finish"].activated_at >= progress["cross"].activated_at

    def test_completion_fraction_tracks_progress(self):
        play = load_library().get("overlap_right")
        state = with_ball(wing_overload_snapshot(), 11)
        result = rehearse(play, state, OVERLAP, Team.HOME, max_seconds=30.0)
        assert result.execution.completion_fraction() == pytest.approx(1.0)

    def test_an_unstarted_execution_is_running_with_nothing_done(self):
        play = load_library().get("overlap_right")
        execution = PlayExecution(play, OVERLAP, Team.HOME)
        assert execution.status is PlayState.RUNNING
        assert execution.completed_steps == ()
        assert execution.completion_fraction() == 0.0


class TestCompletionRules:
    def test_an_arrival_completes_on_reaching_the_anchor(self):
        play = make_play([
            step("go", anchor={"kind": "channel_depth", "flank": "right", "progress": 0.5},
                 timeout=12.0),
        ])
        state = with_ball(wing_overload_snapshot(), 11)
        result = rehearse(play, state, {"wide_creator": 11}, Team.HOME, max_seconds=20.0)
        assert result.completed, result.describe()

    def test_a_sustained_action_completes_after_being_held(self):
        """It is a duration, not a failure, so it must not time out instead."""
        play = make_play([step("hold", action="hold_position", timeout=1.0)])
        state = with_ball(wing_overload_snapshot(), 11)
        result = rehearse(play, state, {"wide_creator": 11}, Team.HOME, max_seconds=6.0)
        assert result.completed, result.describe()
        assert result.execution.progress["hold"].state is StepState.COMPLETE

    def test_an_instantaneous_action_completes_on_activation(self):
        play = make_play([
            step("shout", action="call_for_ball", timeout=2.0),
        ])
        state = with_ball(wing_overload_snapshot(), 11)
        result = rehearse(play, state, {"wide_creator": 11}, Team.HOME, max_seconds=5.0)
        assert result.completed

    def test_an_explicit_completes_when_overrides_the_default(self):
        play = make_play([
            step("go", anchor={"kind": "goal"}, timeout=20.0,
                 completes_when={"kind": "elapsed", "seconds": 0.5}),
        ])
        state = with_ball(wing_overload_snapshot(), 11)
        result = rehearse(play, state, {"wide_creator": 11}, Team.HOME, max_seconds=6.0)
        assert result.completed, "a completes_when must win over unreachable arrival"


class TestFailureModes:
    def test_an_unreachable_arrival_times_out(self):
        play = make_play([
            step("impossible", anchor={"kind": "goal"}, timeout=1.0),
        ])
        state = with_ball(wing_overload_snapshot(), 1)  # the goalkeeper
        result = rehearse(play, state, {"wide_creator": 1}, Team.HOME, max_seconds=8.0)
        assert result.execution.status is PlayState.ABORTED
        assert result.execution.progress["impossible"].state is StepState.TIMED_OUT

    def test_a_trigger_that_never_fires_times_out_from_eligibility(self):
        """Without this a play hangs forever, defeating abort-and-reselect (D-002)."""
        play = make_play([
            step("waiting", anchor={"kind": "ball"}, timeout=1.5,
                 trigger={"kind": "elapsed", "seconds": 999.0}),
        ])
        state = with_ball(wing_overload_snapshot(), 11)
        result = rehearse(play, state, {"wide_creator": 11}, Team.HOME, max_seconds=8.0)
        assert result.execution.status is PlayState.ABORTED
        assert "trigger" in result.execution.progress["waiting"].reason

    def test_abort_if_abandons_the_play(self):
        play = make_play([
            step("run", anchor={"kind": "goal"}, timeout=20.0,
                 abort_if={"kind": "elapsed", "seconds": 0.5}),
        ])
        state = with_ball(wing_overload_snapshot(), 11)
        result = rehearse(play, state, {"wide_creator": 11}, Team.HOME, max_seconds=8.0)
        assert result.execution.status is PlayState.ABORTED
        assert result.execution.progress["run"].state is StepState.ABORTED

    def test_a_disturbance_can_trigger_an_abort(self):
        """D-002 made testable: inject the thing a play should react to."""
        play = make_play([
            step("carry", action="dribble",
                 anchor={"kind": "channel_depth", "flank": "right", "progress": 0.95},
                 timeout=20.0,
                 abort_if={"kind": "pressure_above", "role": "wide_creator", "intensity": 0.6}),
        ])
        state = with_ball(wing_overload_snapshot(), 11)

        def swarm(frame, clock):
            if clock - state.clock_seconds < 1.0:
                return
            carrier = frame.player(11)
            for offset, opponent in zip(
                ((1.5, 0.0), (-1.5, 1.0), (0.0, -1.5)), frame.away.players[:3]
            ):
                opponent.position = np.asarray(carrier.position, dtype=float) + np.array(offset)
                opponent.velocity = np.asarray(carrier.position, dtype=float) - opponent.position

        result = rehearse(
            play, state, {"wide_creator": 11}, Team.HOME, max_seconds=10.0, disturb=swarm
        )
        assert result.execution.status is PlayState.ABORTED
        assert "abort condition" in result.execution.abort_reason

    def test_offside_at_the_moment_of_the_pass_aborts(self):
        """The check §5 specifies, now placeable because triggers exist (Q-009)."""
        play = make_play([
            step("stand", action="hold_position", timeout=0.4),
            step("launch", role="deep_lying_passer", action="pass",
                 anchor={"kind": "behind_line", "metres": 12.0, "flank": "centre",
                         "line_count": 2},
                 depends_on=("stand",), timeout=3.0),
            step("receive", role="runner_in_behind", action="first_touch",
                 anchor={"kind": "ball"}, depends_on=("launch",), timeout=3.0),
        ])
        state = with_ball(wing_overload_snapshot(), 6)
        # #9 sits well beyond the away back line, so the pass is offside when played.
        state.player(9).position = np.array([50.0, 0.0])
        result = rehearse(
            play, state,
            {"wide_creator": 11, "deep_lying_passer": 6, "runner_in_behind": 9},
            Team.HOME, max_seconds=10.0,
        )
        assert result.execution.status is PlayState.ABORTED
        assert any(v.constraint == "offside" for v in result.execution.violations)

    def test_an_onside_pass_does_not_abort(self):
        play = make_play([
            step("launch", role="deep_lying_passer", action="pass",
                 anchor={"kind": "player", "role": "wide_creator"}, timeout=3.0),
            step("receive", role="wide_creator", action="first_touch",
                 anchor={"kind": "ball"}, depends_on=("launch",), timeout=3.0),
        ])
        state = with_ball(wing_overload_snapshot(), 6)
        state.player(11).position = np.array([10.0, 20.0])  # comfortably onside
        result = rehearse(
            play, state, {"wide_creator": 11, "deep_lying_passer": 6},
            Team.HOME, max_seconds=10.0,
        )
        assert not any(v.constraint == "offside" for v in result.execution.violations)


class TestExecutionGuards:
    def test_an_unassigned_role_is_rejected_up_front(self):
        from soccersim.plays.play import PlayError

        play = load_library().get("overlap_right")
        with pytest.raises(PlayError, match="unassigned"):
            PlayExecution(play, {"wide_creator": 11}, Team.HOME)

    def test_updates_after_settling_are_inert(self):
        play = make_play([step("shout", action="call_for_ball", timeout=2.0)])
        state = with_ball(wing_overload_snapshot(), 11)
        execution = PlayExecution(play, {"wide_creator": 11}, Team.HOME)
        execution.update(state)
        assert execution.status is PlayState.COMPLETE
        frames = execution.frames
        execution.update(state)
        assert execution.frames == frames, "a settled play must not keep consuming frames"

    def test_describe_reports_every_step(self):
        play = load_library().get("overlap_right")
        state = with_ball(wing_overload_snapshot(), 11)
        result = rehearse(play, state, OVERLAP, Team.HOME, max_seconds=30.0)
        text = result.describe()
        assert all(s.key in text for s in play.steps)
