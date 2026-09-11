"""The stateful spine — what turns a series of snapshots into a match.

Every M0/M0.5 function is a pure function of one instant. That is why the dashboard
needed building rather than just extending: §2's opponent model is defined by things that
*accumulate* — "historical play patterns... updated after every possession", "pressing
triggers: what provokes a press", "1v1 win rate". None of those can be added as a field
to :class:`~soccersim.domain.state.GameState`, because there is nowhere for them to
accumulate (D-024).

:class:`MatchObserver` is that somewhere. It ingests snapshots, derives events from the
deltas between them, segments possessions, and keeps a **bounded** buffer of recent
frames — bounded by elapsed match time rather than frame count, so a 10 Hz feed and a
1 Hz feed retain the same window of history.

Events are derived, not supplied. Watching ``ball.carrier_id`` change is enough to
recover passes and turnovers, and a pass's direction relative to the passing team's
attacking direction is exactly what press-trigger inference keys on ("initiated on
backpass or sideways pass near opponent box", §3). No action vocabulary needed, which
matters because that arrives with M1.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import Enum

import numpy as np

from ..domain.entities import GamePhase, Team
from ..domain.state import GameState

#: How much recent history to retain, in seconds of match time. Press-trigger detection
#: needs to look back over the seconds before a press began, which sets the floor.
DEFAULT_BUFFER_SECONDS = 12.0

#: Progress change, in metres, for a pass to count as forward or backward rather than
#: sideways.
PASS_DIRECTION_TOLERANCE = 2.0


class EventKind(Enum):
    """Events recoverable from the difference between two snapshots."""

    POSSESSION_START = "possession_start"
    POSSESSION_END = "possession_end"
    PHASE_CHANGE = "phase_change"
    PASS = "pass"
    TURNOVER = "turnover"


class PassDirection(Enum):
    FORWARD = "forward"
    SIDEWAYS = "sideways"
    BACK = "back"


@dataclass(frozen=True)
class MatchEvent:
    """Something that happened between two frames."""

    kind: EventKind
    clock: float
    team: Team | None = None
    detail: dict = field(default_factory=dict)

    def describe(self) -> str:
        team = self.team.value if self.team else "-"
        extras = " ".join(f"{k}={v}" for k, v in sorted(self.detail.items()))
        return f"[{self.clock:7.1f}s] {self.kind.value:<17} {team:<5} {extras}"


@dataclass
class Possession:
    """One team's spell on the ball.

    §6 segments plays as "possession-start to shot/loss-of-possession"; this is the
    observable half of that boundary. Shots need the action vocabulary (M1), so a
    possession currently ends on a turnover, a phase change, or the match stopping.
    """

    team: Team
    start_clock: float
    start_ball_position: np.ndarray
    start_phase: GamePhase
    end_clock: float | None = None
    end_ball_position: np.ndarray | None = None
    end_reason: str = ""
    frames: int = 0
    passes: int = 0
    #: Passes by direction, so a possession can be characterised without replaying it.
    pass_directions: dict[str, int] = field(default_factory=dict)

    @property
    def is_open(self) -> bool:
        return self.end_clock is None

    @property
    def duration(self) -> float:
        if self.end_clock is None:
            return 0.0
        return self.end_clock - self.start_clock

    def progress(self, attacking_direction: int) -> float:
        """Metres of upfield ball progress over the possession."""
        if self.end_ball_position is None:
            return 0.0
        delta = self.end_ball_position[0] - self.start_ball_position[0]
        return float(attacking_direction * delta)


@dataclass
class Frame:
    """One observed snapshot, with its clock pulled out for cheap pruning."""

    clock: float
    state: GameState

    def position_of(self, player_id: int) -> np.ndarray | None:
        try:
            return self.state.player(player_id).position
        except KeyError:
            return None


class MatchObserver:
    """Accumulates match history from a stream of snapshots."""

    def __init__(
        self,
        buffer_seconds: float = DEFAULT_BUFFER_SECONDS,
        max_events: int = 512,
    ) -> None:
        if buffer_seconds <= 0:
            raise ValueError("buffer_seconds must be positive")
        self.buffer_seconds = float(buffer_seconds)
        self.frames: deque[Frame] = deque()
        self.events: deque[MatchEvent] = deque(maxlen=max_events)
        self.possessions: list[Possession] = []
        self.frames_observed = 0

        self._last_carrier: int | None = None
        self._last_carrier_team: Team | None = None
        self._last_carrier_position: np.ndarray | None = None
        self._last_possession: Team | None = None
        self._last_phase: GamePhase | None = None

    # -- ingestion -------------------------------------------------------------

    def observe(self, state: GameState) -> list[MatchEvent]:
        """Ingest one snapshot and return the events it produced.

        Rejects a clock that moves backwards. Replaying history out of order would
        silently corrupt every decayed estimate downstream, and a dropped frame is far
        easier to diagnose than an estimator that quietly disagrees with the match.
        """
        clock = float(state.clock_seconds)
        if self.frames and clock < self.frames[-1].clock:
            raise ValueError(
                f"clock went backwards: {clock:.2f}s after {self.frames[-1].clock:.2f}s. "
                "Snapshots must be observed in order."
            )

        events: list[MatchEvent] = []
        events += self._detect_phase_change(state, clock)
        events += self._detect_possession_change(state, clock)
        events += self._detect_ball_events(state, clock)

        self.frames.append(Frame(clock=clock, state=state))
        self._prune(clock)
        self.frames_observed += 1

        if self.current_possession is not None:
            self.current_possession.frames += 1
            for event in events:
                if event.kind is EventKind.PASS:
                    self.current_possession.passes += 1
                    direction = event.detail.get("direction", "unknown")
                    counts = self.current_possession.pass_directions
                    counts[direction] = counts.get(direction, 0) + 1

        self.events.extend(events)
        self._remember(state, clock)
        return events

    def _prune(self, clock: float) -> None:
        cutoff = clock - self.buffer_seconds
        while len(self.frames) > 1 and self.frames[0].clock < cutoff:
            self.frames.popleft()

    def _remember(self, state: GameState, clock: float) -> None:
        self._last_phase = state.phase
        self._last_possession = state.possession
        if state.ball.carrier_id is not None:
            self._last_carrier = state.ball.carrier_id
            self._last_carrier_team = state.team_of(state.ball.carrier_id)
            self._last_carrier_position = np.array(state.ball.position, dtype=float)

    # -- detection -------------------------------------------------------------

    def _detect_phase_change(self, state: GameState, clock: float) -> list[MatchEvent]:
        if self._last_phase is None or state.phase is self._last_phase:
            return []
        return [
            MatchEvent(
                EventKind.PHASE_CHANGE,
                clock,
                state.possession,
                {"from": self._last_phase.value, "to": state.phase.value},
            )
        ]

    def _detect_possession_change(
        self, state: GameState, clock: float
    ) -> list[MatchEvent]:
        if state.possession is self._last_possession:
            return []
        events: list[MatchEvent] = []
        if self._last_possession is not None:
            events.append(
                MatchEvent(
                    EventKind.POSSESSION_END, clock, self._last_possession,
                    {"reason": "possession_change"},
                )
            )
            self._close_possession(clock, state, "possession_change")
        if state.possession is not None:
            events.append(MatchEvent(EventKind.POSSESSION_START, clock, state.possession))
            self.possessions.append(
                Possession(
                    team=state.possession,
                    start_clock=clock,
                    start_ball_position=np.array(state.ball.position, dtype=float),
                    start_phase=state.phase,
                )
            )
        return events

    def _detect_ball_events(self, state: GameState, clock: float) -> list[MatchEvent]:
        carrier = state.ball.carrier_id
        if carrier is None or carrier == self._last_carrier:
            return []
        if self._last_carrier is None or self._last_carrier_position is None:
            return []

        receiving_team = state.team_of(carrier)
        if receiving_team is not self._last_carrier_team:
            return [
                MatchEvent(
                    EventKind.TURNOVER, clock, receiving_team,
                    {"from": self._last_carrier, "to": carrier},
                )
            ]

        direction = self._pass_direction(state, receiving_team, carrier)
        third = state.pitch.third(
            self._last_carrier_position, state.attacking_direction(receiving_team)
        )
        return [
            MatchEvent(
                EventKind.PASS, clock, receiving_team,
                {
                    "from": self._last_carrier,
                    "to": carrier,
                    "direction": direction.value,
                    "third": third,
                },
            )
        ]

    def _pass_direction(
        self, state: GameState, team: Team, receiver_id: int
    ) -> PassDirection:
        """Direction relative to the passing team's attacking direction."""
        assert self._last_carrier_position is not None
        gain = state.attacking_direction(team) * float(
            state.player(receiver_id).position[0] - self._last_carrier_position[0]
        )
        if gain > PASS_DIRECTION_TOLERANCE:
            return PassDirection.FORWARD
        if gain < -PASS_DIRECTION_TOLERANCE:
            return PassDirection.BACK
        return PassDirection.SIDEWAYS

    def _close_possession(self, clock: float, state: GameState, reason: str) -> None:
        """Close the open possession.

        The end position is taken from the *last frame of the possession*, not from the
        frame that ended it. A possession's progress is how far this team moved the
        ball; measuring to the turnover frame would credit them with wherever the
        opponent happened to win it, which can be many metres upfield.

        This runs before the new frame is buffered, so ``frames[-1]`` is still the last
        frame of the possession being closed.
        """
        current = self.current_possession
        if current is None:
            return
        current.end_clock = clock
        final = self.frames[-1].state if self.frames else state
        current.end_ball_position = np.array(final.ball.position, dtype=float)
        current.end_reason = reason

    # -- read surface ----------------------------------------------------------

    @property
    def current_possession(self) -> Possession | None:
        if self.possessions and self.possessions[-1].is_open:
            return self.possessions[-1]
        return None

    @property
    def clock(self) -> float:
        return self.frames[-1].clock if self.frames else 0.0

    @property
    def latest(self) -> GameState | None:
        return self.frames[-1].state if self.frames else None

    def previous_frame(self) -> Frame | None:
        """The frame before the latest, for frame-to-frame displacement."""
        return self.frames[-2] if len(self.frames) >= 2 else None

    def displacement(self, player_id: int) -> np.ndarray | None:
        """A player's movement between the last two observed frames.

        Returns ``None`` when there is no prior frame or the player is absent from
        either, so a substitution cannot masquerade as a teleport.
        """
        previous = self.previous_frame()
        if previous is None or not self.frames:
            return None
        before = previous.position_of(player_id)
        after = self.frames[-1].position_of(player_id)
        if before is None or after is None:
            return None
        return np.asarray(after, dtype=float) - np.asarray(before, dtype=float)

    def recent_events(
        self,
        kinds: tuple[EventKind, ...] | None = None,
        since: float | None = None,
        team: Team | None = None,
    ) -> list[MatchEvent]:
        """Buffered events, filtered. Oldest first."""
        out = []
        for event in self.events:
            if kinds is not None and event.kind not in kinds:
                continue
            if since is not None and event.clock < since:
                continue
            if team is not None and event.team is not team:
                continue
            out.append(event)
        return out

    def completed_possessions(self, team: Team | None = None) -> list[Possession]:
        return [
            possession
            for possession in self.possessions
            if not possession.is_open and (team is None or possession.team is team)
        ]

    def describe(self) -> str:
        return (
            f"{self.frames_observed} frames observed, {len(self.frames)} buffered "
            f"({self.buffer_seconds:.0f}s window), {len(self.possessions)} possessions, "
            f"{len(self.events)} events, clock {self.clock:.1f}s"
        )
