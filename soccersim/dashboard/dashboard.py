"""The information dashboard — module 1's read surface.

Owns the observer and the estimators, and exposes what the ranking layer will ask:
where the opponent's block is, how they mark, what provokes their press, and how
predictable our own recent play has been.

Asymmetric on purpose. For **our own team** it reports measurements only: we chose our
scheme, so inferring it would be measuring our own intent. For the **opponent** it runs
the estimators, because that is the half §2 describes as growing over time.

Every inferred value arrives as an :class:`~soccersim.dashboard.estimate.Estimate`, so
a consumer has to pass through ``mature_value`` or ``require_mature`` to act on it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..domain.entities import Team
from ..domain.state import GameState
from .book import PlayBook
from .estimate import DEFAULT_HALF_LIFE, Estimate
from .marking import MarkingModel, MarkingScheme
from .measurements import (
    BlockType,
    Pressure,
    TeamShape,
    pressure_on_ball,
    situation_key,
    team_shape,
)
from .observer import DEFAULT_BUFFER_SECONDS, MatchObserver, Possession
from .pressing import PressingModel


@dataclass
class OpponentModel:
    """Everything currently inferred about the opposition."""

    team: Team
    clock: float
    shape: TeamShape
    marking_scheme: Estimate[MarkingScheme]
    marking_assignments: dict[int, Estimate[int]]
    zones: dict[int, tuple[np.ndarray, float]]
    press_intensity: Estimate[float]
    press_frequency: Estimate[float]
    press_triggers: dict[tuple[str, str], float]
    possessions_observed: int = 0

    @property
    def block(self) -> BlockType | None:
        return self.shape.block

    def marker_of(self, attacker_id: int) -> int | None:
        """Defender marking a given attacker, only if the estimate is mature.

        Returns a bare id rather than an estimate because this is the acting path:
        §5's ``mismatch_bonus`` wants "the weak defender on our man" or nothing.
        """
        for defender_id, estimate in self.marking_assignments.items():
            if estimate.is_mature and estimate.value == attacker_id:
                return defender_id
        return None

    def describe(self) -> str:
        lines = [
            f"opponent ({self.team.value}) at {self.clock:.1f}s — "
            f"{self.possessions_observed} possessions observed",
            f"  shape   {self.shape.describe()}",
            f"  marking {self.marking_scheme.describe('scheme')}",
        ]
        if self.marking_assignments:
            pairs = ", ".join(
                f"{defender}->{estimate.value}"
                + ("" if estimate.is_mature else "?")
                for defender, estimate in sorted(self.marking_assignments.items())
            )
            lines.append(f"          assignments: {pairs}")
        if self.zones:
            lines.append(f"          {len(self.zones)} defenders holding zones")
        lines.append(
            f"  press   {self.press_intensity.describe('intensity')}  "
            f"{self.press_frequency.describe('frequency')}"
        )
        triggers = (
            ", ".join(f"{d}/{t} {r:.0%}" for (d, t), r in sorted(self.press_triggers.items()))
            or "none identified"
        )
        lines.append(f"          triggers: {triggers}")
        return "\n".join(lines)


@dataclass
class TeamReport:
    """Measured state of our own team — no inference."""

    shape: TeamShape
    pressure_on_ball: Pressure | None
    situation: tuple[str, str, str]
    possession: Team | None

    def describe(self) -> str:
        pressure = (
            f"carrier #{self.pressure_on_ball.carrier_id} "
            f"pressed by {self.pressure_on_ball.count} "
            f"(nearest {self.pressure_on_ball.nearest_arrival:.2f}s, "
            f"intensity {self.pressure_on_ball.intensity:.2f})"
            if self.pressure_on_ball
            else "nobody on the ball"
        )
        return (
            f"us ({self.shape.team.value})\n"
            f"  shape   {self.shape.describe()}\n"
            f"  ball    {pressure}\n"
            f"  situation {'/'.join(self.situation)}  possession "
            f"{self.possession.value if self.possession else '-'}"
        )


class Dashboard:
    """Module 1: tracks our state, models the opponent, remembers our own plays."""

    def __init__(
        self,
        our_team: Team = Team.HOME,
        buffer_seconds: float = DEFAULT_BUFFER_SECONDS,
        half_life: float = DEFAULT_HALF_LIFE,
    ) -> None:
        self.our_team = our_team
        self.observer = MatchObserver(buffer_seconds=buffer_seconds)
        self.marking = MarkingModel(our_team.other, half_life=half_life)
        self.pressing = PressingModel(our_team.other, half_life=half_life)
        self.book = PlayBook()

    # -- ingestion -------------------------------------------------------------

    def observe(self, state: GameState) -> list:
        """Ingest one snapshot; returns the events it produced.

        Order matters: the observer must record the frame first, because both
        estimators read frame-to-frame displacement and the freshly buffered event list
        through it.
        """
        events = self.observer.observe(state)
        self.marking.observe(state, self.observer)
        self.pressing.observe(state, self.observer)
        return events

    def observe_all(self, states) -> None:
        for state in states:
            self.observe(state)
        self.pressing.flush(self.observer.clock)

    # -- read surface ----------------------------------------------------------

    @property
    def clock(self) -> float:
        return self.observer.clock

    def team_report(self) -> TeamReport | None:
        state = self.observer.latest
        if state is None:
            return None
        return TeamReport(
            shape=team_shape(state.team_state(self.our_team), state.pitch),
            pressure_on_ball=pressure_on_ball(state),
            situation=situation_key(state, self.our_team),
            possession=state.possession,
        )

    def opponent_model(self) -> OpponentModel | None:
        state = self.observer.latest
        if state is None:
            return None
        clock = self.clock
        return OpponentModel(
            team=self.our_team.other,
            clock=clock,
            shape=team_shape(state.opponents_of(self.our_team), state.pitch),
            marking_scheme=self.marking.scheme(clock),
            marking_assignments=self.marking.assignments(clock),
            zones=self.marking.zones(clock),
            press_intensity=self.pressing.intensity(clock),
            press_frequency=self.pressing.frequency(clock),
            press_triggers=self.pressing.triggers(clock),
            possessions_observed=len(
                self.observer.completed_possessions(self.our_team.other)
            ),
        )

    def situation(self) -> tuple[str, str, str] | None:
        state = self.observer.latest
        return situation_key(state, self.our_team) if state else None

    def record_play(self, play_key: str) -> None:
        """Log that we ran a play in the current situation (§5 predictability)."""
        situation = self.situation()
        if situation is None:
            raise ValueError("cannot record a play before observing any state")
        self.book.record_use(play_key, situation, self.clock)

    def predictability(self, play_key: str) -> float:
        situation = self.situation()
        if situation is None:
            return 0.0
        return self.book.predictability(play_key, situation, self.clock)

    def possessions(self, team: Team | None = None) -> list[Possession]:
        return self.observer.completed_possessions(team)

    def report(self) -> str:
        parts = [self.observer.describe()]
        team = self.team_report()
        if team:
            parts.append(team.describe())
        opponent = self.opponent_model()
        if opponent:
            parts.append(opponent.describe())
        parts.append(self.book.describe(self.clock))
        return "\n".join(parts)
