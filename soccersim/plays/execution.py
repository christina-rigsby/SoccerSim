"""Running a play forward through its triggers.

Instantiation answers "could we start this play here". Execution answers "is it still
working" — and without it the triggers are never actually fired, which would leave the
most error-prone part of the design untested.

Each step moves ``PENDING -> ACTIVE -> COMPLETE``, or out sideways into ``TIMED_OUT`` or
``ABORTED``. A step becomes *eligible* when its dependencies are complete, *activates*
when its trigger fires, and completes by one of five rules depending on what kind of
action it is (see :meth:`PlayExecution._completed`).

Two things here are design doc requirements made concrete rather than aspirational:

**Abort mid-play** (D-002). A step's ``abort_if`` and its ``timeout`` both abandon the
play, with a recorded reason. "Plans are receding-horizon, not one-shot — be willing to
abort mid-play and reselect" needs a mechanism, and this is it.

**Offside at the moment of the pass** (§5). Offside is checked when a ball-releasing step
*fires*, against its receivers, rather than at selection time. A run beyond the line is
legal to make; you are only offside if the ball is played to you while you are there.
Checking at selection would reject nearly every counter-attack. Q-009's resolution is
what makes the correct timing expressible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Mapping

import numpy as np

from ..constraints.feasibility import Violation, is_offside
from ..domain.entities import Team
from ..domain.state import GameState
from .anchors import AnchorError, PlayContext
from .play import Play, PlayError
from .triggers import BallPlayedBy, TriggerContext, TriggerError


class StepState(Enum):
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETE = "complete"
    TIMED_OUT = "timed_out"
    ABORTED = "aborted"

    @property
    def is_terminal(self) -> bool:
        return self in (StepState.COMPLETE, StepState.TIMED_OUT, StepState.ABORTED)

    @property
    def is_failure(self) -> bool:
        return self in (StepState.TIMED_OUT, StepState.ABORTED)


class PlayState(Enum):
    RUNNING = "running"
    COMPLETE = "complete"
    ABORTED = "aborted"


@dataclass
class StepProgress:
    """Lifecycle of one step within one execution."""

    key: str
    state: StepState = StepState.PENDING
    eligible_since: float | None = None
    activated_at: float | None = None
    finished_at: float | None = None
    reason: str = ""

    def describe(self) -> str:
        timing = ""
        if self.activated_at is not None:
            timing = f" active@{self.activated_at:.1f}s"
        if self.finished_at is not None:
            timing += f" ended@{self.finished_at:.1f}s"
        return f"{self.key:<18}{self.state.value:<11}{timing}{'  ' + self.reason if self.reason else ''}"


@dataclass
class ExecutionUpdate:
    """What changed in one frame."""

    clock: float
    activated: tuple[str, ...] = ()
    completed: tuple[str, ...] = ()
    failed: tuple[str, ...] = ()
    violations: tuple[Violation, ...] = ()
    status: PlayState = PlayState.RUNNING

    @property
    def changed(self) -> bool:
        return bool(self.activated or self.completed or self.failed)


class PlayExecution:
    """Drives one play through a stream of snapshots."""

    def __init__(
        self,
        play: Play,
        assignment: Mapping[str, int],
        team: Team = Team.HOME,
        grid_resolution: float = 2.0,
    ) -> None:
        missing = sorted(set(play.roles()) - set(assignment))
        if missing:
            raise PlayError(
                f"play {play.key!r} needs roles {', '.join(missing)}, which are unassigned"
            )
        self.play = play
        self.assignment = dict(assignment)
        self.team = team
        self.grid_resolution = grid_resolution
        self.progress: dict[str, StepProgress] = {
            step.key: StepProgress(key=step.key) for step in play.steps
        }
        self.status = PlayState.RUNNING
        self.abort_reason = ""
        self.started_at: float | None = None
        self.finished_at: float | None = None
        self.held_ball: set[str] = set()
        self.violations: list[Violation] = []
        self.frames = 0

    # -- ingestion -------------------------------------------------------------

    def update(self, state: GameState) -> ExecutionUpdate:
        """Advance the play by one observed snapshot."""
        clock = float(state.clock_seconds)
        if self.started_at is None:
            self.started_at = clock
        if self.status is not PlayState.RUNNING:
            return ExecutionUpdate(clock=clock, status=self.status)

        self.frames += 1
        context = PlayContext(
            state=state, team=self.team, assignment=self.assignment,
            grid_resolution=self.grid_resolution,
        )
        self._note_ball_holder(state)

        activated: list[str] = []
        completed: list[str] = []
        failed: list[str] = []
        new_violations: list[Violation] = []

        for key in self.play.topological_order():
            step = self.play.step(key)
            progress = self.progress[key]
            if progress.state.is_terminal:
                continue

            trigger_context = self._trigger_context(context, clock, progress)

            if progress.state is StepState.PENDING:
                if not all(
                    self.progress[dep].state is StepState.COMPLETE
                    for dep in step.depends_on
                ):
                    continue
                if progress.eligible_since is None:
                    progress.eligible_since = clock
                    trigger_context.eligible_since = clock
                if not self._safe(step.trigger.evaluate, trigger_context, key, "trigger"):
                    # A step whose trigger never fires has to give up too. The timeout
                    # runs from *eligibility*, not from activation: otherwise a play
                    # whose trigger condition never materialises waits forever, which is
                    # exactly the hang that abort-and-reselect (D-002) exists to avoid.
                    if clock - progress.eligible_since > step.timeout:
                        progress.state = StepState.TIMED_OUT
                        progress.reason = (
                            f"trigger did not fire within {step.timeout:.1f}s "
                            f"({step.trigger.describe()})"
                        )
                        progress.finished_at = clock
                        self._abort(key, f"{key!r} trigger never fired", clock)
                        failed.append(key)
                        break
                    continue
                progress.state = StepState.ACTIVE
                progress.activated_at = clock
                activated.append(key)
                offside = self._offside_at_release(step, context, clock)
                if offside is not None:
                    new_violations.append(offside)
                    self._abort(key, f"offside when {key!r} was played", clock)
                    failed.append(key)
                    break
                trigger_context = self._trigger_context(context, clock, progress)

            if progress.state is StepState.ACTIVE:
                if step.abort_if is not None and self._safe(
                    step.abort_if.evaluate, trigger_context, key, "abort_if"
                ):
                    self._abort(key, f"{key!r} abort condition fired", clock)
                    failed.append(key)
                    break
                if self._completed(step, context, trigger_context):
                    progress.state = StepState.COMPLETE
                    progress.finished_at = clock
                    completed.append(key)
                elif clock - (progress.activated_at or clock) > step.timeout:
                    progress.state = StepState.TIMED_OUT
                    progress.reason = f"not complete within {step.timeout:.1f}s"
                    progress.finished_at = clock
                    self._abort(key, f"{key!r} timed out", clock)
                    failed.append(key)
                    break

        self.violations.extend(new_violations)
        if self.status is PlayState.RUNNING and self._all_terminal_complete():
            self.status = PlayState.COMPLETE
            self.finished_at = clock

        return ExecutionUpdate(
            clock=clock,
            activated=tuple(activated),
            completed=tuple(completed),
            failed=tuple(failed),
            violations=tuple(new_violations),
            status=self.status,
        )

    def run(self, states: Iterable[GameState]) -> ExecutionUpdate:
        """Drive the play over a whole stream, stopping when it settles."""
        last = ExecutionUpdate(clock=0.0, status=self.status)
        for state in states:
            last = self.update(state)
            if self.status is not PlayState.RUNNING:
                break
        return last

    # -- internals -------------------------------------------------------------

    def _trigger_context(
        self, context: PlayContext, clock: float, progress: StepProgress
    ) -> TriggerContext:
        return TriggerContext(
            play=context,
            clock=clock,
            eligible_since=progress.eligible_since,
            completed=frozenset(
                key for key, p in self.progress.items() if p.state is StepState.COMPLETE
            ),
            held_ball=frozenset(self.held_ball),
            play_started_at=self.started_at or clock,
        )

    def _note_ball_holder(self, state: GameState) -> None:
        """Record which of our roles has had the ball, for ``ball_played_by``."""
        carrier = state.ball.carrier_id
        if carrier is None:
            return
        for role, player_id in self.assignment.items():
            if player_id == carrier:
                self.held_ball.add(role)

    def _safe(self, evaluate, trigger_context, key: str, what: str) -> bool:
        """Evaluate a predicate, turning an unresolvable anchor into ``False``.

        An anchor that cannot resolve right now (nobody has the ball, the opponent has
        too few defenders for a line) means the condition is simply not met yet — not
        that the play is broken. Raising would abort plays for transient reasons.
        """
        try:
            return bool(evaluate(trigger_context))
        except (AnchorError, TriggerError, KeyError, ValueError):
            return False

    def _completed(self, step, context: PlayContext, trigger_context) -> bool:
        """Whether a step is done.

        Five rules, in order:

        1. an explicit ``completes_when`` always wins;
        2. a ball-releasing action completes when the ball has left the player;
        3. a *sustained* action completes once held for its ``timeout`` — it is a
           duration, not a failure, so it must not time out instead;
        4. an anchored action completes on arrival within its tolerance;
        5. anything else is instantaneous and completes on activation.
        """
        if step.completes_when is not None:
            return self._safe(
                step.completes_when.evaluate, trigger_context, step.key, "completes_when"
            )

        spec = step.action_spec
        if spec.releases_ball:
            return self._safe(
                BallPlayedBy(role=step.role).evaluate, trigger_context, step.key, "release"
            )
        if spec.sustained:
            activated = self.progress[step.key].activated_at
            return activated is not None and trigger_context.clock - activated >= step.timeout
        if step.anchor is not None:
            try:
                target = step.anchor.resolve(context)
                position = context.player(step.role).position
            except (AnchorError, KeyError, ValueError):
                return False
            distance = float(np.linalg.norm(np.asarray(position, dtype=float) - target))
            return distance <= step.arrival_tolerance
        return True

    def _offside_at_release(
        self, step, context: PlayContext, clock: float
    ) -> Violation | None:
        """Check offside for the receivers of a pass, at the instant it is played."""
        if not step.action_spec.releases_ball:
            return None
        instantiated_receivers = [
            self.assignment[dependant.role]
            for dependant in self.play.steps
            if step.key in dependant.depends_on and dependant.role in self.assignment
        ]
        if not instantiated_receivers:
            return None

        state = context.state
        defenders = [d.position for d in state.opponents_of(self.team).available()]
        direction = context.attacking_direction
        for receiver_id in sorted(set(instantiated_receivers)):
            try:
                receiver = state.player(receiver_id)
            except KeyError:
                continue
            if is_offside(receiver.position, state.ball.position, defenders, direction):
                return Violation(
                    "offside",
                    f"player {receiver.label} was beyond the second-last defender when "
                    f"{step.key!r} was played at {clock:.1f}s",
                )
        return None

    def _abort(self, key: str, reason: str, clock: float) -> None:
        progress = self.progress[key]
        if progress.state is not StepState.TIMED_OUT:
            progress.state = StepState.ABORTED
            progress.reason = reason
            progress.finished_at = clock
        self.status = PlayState.ABORTED
        self.abort_reason = reason
        self.finished_at = clock

    def _all_terminal_complete(self) -> bool:
        return all(
            self.progress[key].state is StepState.COMPLETE
            for key in self.play.terminal_steps()
        )

    # -- read surface ----------------------------------------------------------

    @property
    def completed_steps(self) -> tuple[str, ...]:
        return tuple(
            key for key, p in self.progress.items() if p.state is StepState.COMPLETE
        )

    @property
    def duration(self) -> float:
        if self.started_at is None:
            return 0.0
        return (self.finished_at or self.started_at) - self.started_at

    def completion_fraction(self) -> float:
        return len(self.completed_steps) / len(self.play.steps)

    def describe(self) -> str:
        lines = [
            f"{self.play.key}: {self.status.value}"
            + (f" — {self.abort_reason}" if self.abort_reason else "")
            + f"  ({len(self.completed_steps)}/{len(self.play.steps)} steps, "
            f"{self.frames} frames, {self.duration:.1f}s)"
        ]
        for key in self.play.topological_order():
            lines.append("  " + self.progress[key].describe())
        for violation in self.violations:
            lines.append(f"  ! {violation}")
        return "\n".join(lines)
