"""Match events (spec §4.5 event types).

Events are stored from a team's perspective: ``Event.team`` is the team the event type
describes (``possession_won`` for the winner, ``possession_lost`` for the loser, and so
on). Neutral events (``ball_out``) carry ``team=None`` and apply to both.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .state import MatchState


@dataclass
class Event:
    t: float
    tick: int
    type: str
    team: int | None
    player: int = -1
    pos: tuple[float, float] = (0.0, 0.0)
    data: dict[str, Any] = field(default_factory=dict)

    def applies_to(self, team: int) -> bool:
        return self.team is None or self.team == team

    def to_dict(self) -> dict[str, Any]:
        return {
            "t": round(self.t, 2), "type": self.type, "team": self.team, "player": self.player,
            "pos": [round(self.pos[0], 2), round(self.pos[1], 2)], **({"data": self.data} if self.data else {}),
        }


class EventLog:
    """Append-only event list with a per-team query."""

    def __init__(self) -> None:
        self.events: list[Event] = []

    def add(self, ev: Event) -> None:
        self.events.append(ev)

    def since(self, team: int, since_tick: int, types: tuple[str, ...] | str | None = None) -> list[Event]:
        if isinstance(types, str):
            types = (types,)
        out = []
        for ev in reversed(self.events):
            if ev.tick < since_tick:
                break
            if ev.applies_to(team) and (types is None or ev.type in types):
                out.append(ev)
        out.reverse()
        return out

    def happened(self, team: int, etype: str, since_tick: int) -> bool:
        for ev in reversed(self.events):
            if ev.tick < since_tick:
                return False
            if ev.type == etype and ev.applies_to(team):
                return True
        return False

    def __len__(self) -> int:
        return len(self.events)


def emit(state: MatchState, etype: str, team: int | None, player: int = -1, pos=None, **data) -> None:
    """Record an event at the current tick (``pos`` defaults to the ball)."""
    p = state.ball.pos if pos is None else pos
    state.events.add(Event(state.t, state.tick, etype, team, player, (float(p[0]), float(p[1])), data))
