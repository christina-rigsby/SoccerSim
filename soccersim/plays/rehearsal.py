"""Drive a play to completion in a closed loop — test scaffolding for the executor.

Instantiation and the structural checks can be tested on a single snapshot, but triggers
cannot: nothing fires unless the world changes. This module changes the world in the
crudest way that exercises the real machinery — players step toward whatever their
current step's anchor resolves to *this frame*, and the ball moves when a releasing step
activates.

That closed loop is the point. The executor decides what should be happening and the
rehearsal makes it happen, so a play that reaches ``COMPLETE`` has genuinely had every
trigger fire, every completion rule evaluate, and every dependency respected. Because
anchors are re-resolved every frame, it also exercises the flexibility that motivated the
design: a player chasing ``max_control`` follows a target that moves as the field changes.

**This is not the simulator** (D-011, D-026). No ball physics, no opponent reaction, no
decision-making, and the opponents stand still. It proves the play machinery runs; it
proves nothing about whether a play would work against a real defence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Mapping

import numpy as np

from ..domain.entities import BallPhase, BallState, Team
from ..domain.state import GameState, TeamState
from .anchors import AnchorError, PlayContext
from .execution import PlayExecution, PlayState, StepState
from .play import Play

#: Rehearsal ball speed, m/s. Matches the space layer's default ground pass.
BALL_SPEED = 15.0

#: How close the ball must get to a pass target before the receiver is credited with it.
RECEIVE_RADIUS = 1.5


@dataclass
class _Flight:
    """A pass in the air.

    Held by the rehearsal rather than read off the step, because a releasing step
    *completes the moment the ball leaves the player* — the carrier goes to ``None`` in
    flight, which is precisely what "has played the ball" means. So by the time the ball
    is halfway there the step is already done, and anything keying off its state would
    stop moving the ball and leave it frozen in mid-air.
    """

    target: np.ndarray
    receiver: int | None


@dataclass
class RehearsalResult:
    execution: PlayExecution
    frames: list[GameState] = field(default_factory=list)

    @property
    def status(self) -> PlayState:
        return self.execution.status

    @property
    def completed(self) -> bool:
        return self.execution.status is PlayState.COMPLETE

    def describe(self) -> str:
        return (
            f"{len(self.frames)} frames rehearsed\n" + self.execution.describe()
        )


def _player_destination(
    execution: PlayExecution, context: PlayContext, player_id: int
) -> np.ndarray | None:
    """Where this player should currently be heading.

    Their first step that is not yet complete, provided its anchor is a player
    destination. Re-resolved every frame, which is what makes a live anchor live.
    """
    for key in execution.play.topological_order():
        step = execution.play.step(key)
        if execution.assignment.get(step.role) != player_id:
            continue
        progress = execution.progress[key]
        if progress.state.is_terminal:
            continue
        if step.anchor is None or step.action_spec.releases_ball:
            continue
        try:
            return step.anchor.resolve(context)
        except (AnchorError, KeyError, ValueError):
            return None
    return None


def _active_release(execution: PlayExecution):
    """The ball-releasing step currently in flight, if any."""
    for key in execution.play.topological_order():
        step = execution.play.step(key)
        if (
            step.action_spec.releases_ball
            and execution.progress[key].state is StepState.ACTIVE
        ):
            return step
    return None


def _receiver_of(execution: PlayExecution, step_key: str) -> int | None:
    for dependant in execution.play.steps:
        if step_key in dependant.depends_on:
            return execution.assignment.get(dependant.role)
    return None


def rehearse(
    play: Play,
    state: GameState,
    assignment: Mapping[str, int],
    team: Team = Team.HOME,
    dt: float = 0.2,
    max_seconds: float = 25.0,
    disturb: Callable[[GameState, float], None] | None = None,
) -> RehearsalResult:
    """Run ``play`` forward from ``state`` until it completes, aborts, or times out.

    ``disturb`` is called with each new frame before it is observed, so a test can
    inject the thing a play should react to — an opponent closing down the carrier, say —
    and check that ``abort_if`` fires. That is how D-002's "be willing to abort mid-play"
    gets verified rather than assumed.
    """
    execution = PlayExecution(play, assignment, team=team)
    result = RehearsalResult(execution=execution)

    current = _clone(state)
    clock = float(current.clock_seconds)
    deadline = clock + max_seconds
    flight: _Flight | None = None

    while clock <= deadline:
        if disturb is not None:
            disturb(current, clock)
        result.frames.append(current)
        execution.update(current)
        if execution.status is not PlayState.RUNNING:
            break

        clock += dt
        current, flight = _advance(execution, current, clock, dt, team, flight)

    return result


def _clone(state: GameState) -> GameState:
    """A shallow copy with independent player and ball objects."""
    from dataclasses import replace as dc_replace

    def clone_team(team_state: TeamState) -> TeamState:
        return TeamState(
            team=team_state.team,
            players=[
                dc_replace(
                    player,
                    position=np.array(player.position, dtype=float),
                    velocity=np.array(player.velocity, dtype=float),
                )
                for player in team_state.players
            ],
            attacking_direction=team_state.attacking_direction,
        )

    return GameState(
        pitch=state.pitch,
        home=clone_team(state.home),
        away=clone_team(state.away),
        ball=BallState(
            position=np.array(state.ball.position, dtype=float),
            velocity=np.array(state.ball.velocity, dtype=float),
            height=state.ball.height,
            carrier_id=state.ball.carrier_id,
            phase=state.ball.phase,
        ),
        score=state.score,
        clock_seconds=state.clock_seconds,
        phase=state.phase,
        possession=state.possession,
    )


def _advance(
    execution: PlayExecution,
    state: GameState,
    clock: float,
    dt: float,
    team: Team,
    flight: _Flight | None,
) -> tuple[GameState, _Flight | None]:
    """Build the next frame: move the assigned players, then move the ball."""
    nxt = _clone(state)
    nxt.clock_seconds = clock
    context = PlayContext(state=state, team=team, assignment=execution.assignment)

    for player_id in set(execution.assignment.values()):
        try:
            player = nxt.player(player_id)
        except KeyError:
            continue
        destination = _player_destination(execution, context, player_id)
        if destination is None:
            player.velocity = np.zeros(2)
            continue
        capability = player.effective_capability()
        offset = destination - player.position
        distance = float(np.linalg.norm(offset))
        stride = capability.max_speed * dt
        if distance <= stride or distance < 1e-9:
            moved = destination.copy()
        else:
            moved = player.position + offset / distance * stride
        player.velocity = (moved - player.position) / dt
        player.position = moved

    # A newly activated release starts a flight, if one is not already under way.
    if flight is None:
        release = _active_release(execution)
        if release is not None and release.anchor is not None:
            try:
                flight = _Flight(
                    target=release.anchor.resolve(context),
                    receiver=_receiver_of(execution, release.key),
                )
            except (AnchorError, KeyError, ValueError):
                flight = None

    if flight is not None:
        ball = np.array(nxt.ball.position, dtype=float)
        offset = flight.target - ball
        distance = float(np.linalg.norm(offset))
        stride = BALL_SPEED * dt
        if distance <= max(stride, RECEIVE_RADIUS):
            receiver = flight.receiver
            nxt.ball = BallState(
                position=(
                    np.array(nxt.player(receiver).position, dtype=float)
                    if receiver is not None
                    else flight.target
                ),
                carrier_id=receiver,
                phase=BallPhase.ON_GROUND,
            )
            return nxt, None
        nxt.ball = BallState(
            position=ball + offset / distance * stride,
            velocity=offset / distance * BALL_SPEED,
            carrier_id=None,
            phase=BallPhase.IN_FLIGHT,
        )
        return nxt, flight

    # Nothing in flight: the ball stays with whoever has it.
    if nxt.ball.carrier_id is not None:
        try:
            nxt.ball.position = np.array(
                nxt.player(nxt.ball.carrier_id).position, dtype=float
            )
        except KeyError:
            pass
    return nxt, None
