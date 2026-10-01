"""Simulator state (spec §7.1), stored as NumPy arrays in absolute coordinates.

Players are indexed ``0..21``: home ``0..10`` (attacks +x), away ``11..21`` (attacks -x).
Each team reasons in its own attacking frame; because the frame is a 180° rotation,
converting is multiplication by the team's direction ``d = +1 | -1``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..schema.vocab import CAPABILITIES
from .events import EventLog

CAP_INDEX = {c: i for i, c in enumerate(CAPABILITIES)}
N_PER_TEAM = 11
HOME, AWAY = 0, 1
DIRECTION = (1.0, -1.0)


def team_of(player: int) -> int:
    return HOME if player < N_PER_TEAM else AWAY


def team_players(team: int) -> range:
    return range(team * N_PER_TEAM, (team + 1) * N_PER_TEAM)


@dataclass
class Flight:
    """A ball in flight after a pass, cross, clear or shot."""

    kind: str                      # pass | shot | clear
    team: int
    passer: int
    receiver: int                  # intended receiver, or -1
    style: str
    target: np.ndarray             # absolute landing / arrival point
    release_t: float
    air: bool
    duration: float                # seconds until the ball reaches target
    intercept_player: int = -1     # sampled interceptor (ground passes)
    intercept_point: np.ndarray | None = None
    intercept_t: float = 0.0
    offside: frozenset[int] = frozenset()
    shot_outcome: str = ""         # goal | caught | parried_corner | off_target
    xg: float = 0.0
    header: bool = False


@dataclass
class Ball:
    pos: np.ndarray = field(default_factory=lambda: np.zeros(2))
    vel: np.ndarray = field(default_factory=lambda: np.zeros(2))
    height: str = "ground"         # ground | air
    owner: int = -1
    last_touch_team: int = -1
    last_touch_player: int = -1
    flight: Flight | None = None
    owner_since: float = 0.0
    last_aerial_t: float = -99.0


@dataclass
class Restart:
    type: str                      # kickoff | goal_kick | corner | throw_in | free_kick
    team: int
    pos: np.ndarray
    ready_t: float
    taker: int = -1


@dataclass
class MatchState:
    pos: np.ndarray                # (22, 2)
    vel: np.ndarray                # (22, 2)
    caps: np.ndarray               # (22, 13) in [0, 1]
    stamina: np.ndarray            # (22,) current stamina in [0, 1]
    slots: list[str]               # formation slot names
    kinds: list[str]               # slot kinds (GK, CB, FB, DM, CM, AM, W, ST)
    base_out: np.ndarray           # (22, 2) out-of-possession base, team frame
    base_in: np.ndarray            # (22, 2) in-possession base, team frame
    formations: tuple[str, str]
    ball: Ball = field(default_factory=Ball)
    t: float = 0.0
    tick: int = 0
    minute0: float = 0.0           # match minute at t = 0 (scenarios start mid-match)
    score: list[int] = field(default_factory=lambda: [0, 0])
    possession: int | None = None  # team in control (owner or own pass in flight); None = loose
    last_control_team: int | None = None
    restart: Restart | None = None
    events: EventLog = field(default_factory=EventLog)
    tackle_cooldown: np.ndarray = field(default_factory=lambda: np.zeros(22))
    stun_until: np.ndarray = field(default_factory=lambda: np.zeros(22))
    touch_cooldown: np.ndarray = field(default_factory=lambda: np.zeros(22))

    @property
    def minute(self) -> float:
        return self.minute0 + self.t / 60.0

    def cap(self, player: int, name: str) -> float:
        return float(self.caps[player, CAP_INDEX[name]])

    def gk(self, team: int) -> int:
        for i in team_players(team):
            if self.kinds[i] == "GK":
                return i
        return -1

    def copy(self) -> MatchState:
        import copy as _copy

        return _copy.deepcopy(self)
