"""Players, the ball, and the waypoint primitive.

Fatigue is modelled as *degradation of capability* rather than an additive penalty
(D-006): a tired player is slower, which automatically makes them a poor fit for
high-sprint-demand roles specifically, instead of penalising them uniformly whatever
they are asked to do.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum

import numpy as np

from .pitch import vec


class Team(Enum):
    HOME = "home"
    AWAY = "away"

    @property
    def other(self) -> "Team":
        return Team.AWAY if self is Team.HOME else Team.HOME


class BallPhase(Enum):
    """Coarse ball state, from design doc §2 ("in flight, on ground, contested")."""

    ON_GROUND = "on_ground"
    IN_FLIGHT = "in_flight"
    CONTESTED = "contested"
    DEAD = "dead"


class GamePhase(Enum):
    """Match phase, from design doc §2."""

    KICKOFF = "kickoff"
    OPEN_PLAY = "open_play"
    TRANSITION = "transition"
    SET_PIECE = "set_piece"


# Stamina of 0 does not make a player immobile — it makes them notably slower.
# The floor is a guess (see D-006); it is not fitted to anything.
FATIGUE_FLOOR = 0.75


@dataclass(frozen=True)
class CapabilityProfile:
    """A player's physical envelope, in SI units.

    ``reaction_time`` is charged once per arrival-time computation and covers
    perception plus decision lag.
    """

    max_speed: float = 7.8  # m/s; ~28 km/h, a quick outfield player
    max_accel: float = 6.5  # m/s^2
    reaction_time: float = 0.20  # s

    def degraded(self, stamina: float) -> "CapabilityProfile":
        """This profile scaled by ``stamina`` in [0, 1] (D-006).

        Reaction time lengthens as stamina falls; speed and acceleration shrink.
        """
        s = float(np.clip(stamina, 0.0, 1.0))
        scale = FATIGUE_FLOOR + (1.0 - FATIGUE_FLOOR) * s
        return CapabilityProfile(
            max_speed=self.max_speed * scale,
            max_accel=self.max_accel * scale,
            reaction_time=self.reaction_time / scale,
        )


@dataclass
class PlayerState:
    """One player at one instant.

    ``role`` is the positional label ("RW", "LB", ...). Role *requirements* in the
    ranking graph (§4) are a separate, richer concept and arrive with M1.
    """

    player_id: int
    team: Team
    position: np.ndarray
    velocity: np.ndarray = field(default_factory=lambda: vec(0.0, 0.0))
    role: str = ""
    capability: CapabilityProfile = field(default_factory=CapabilityProfile)
    stamina: float = 1.0
    available: bool = True  # False when injured, carded off, or otherwise out

    def __post_init__(self) -> None:
        self.position = np.asarray(self.position, dtype=float)
        self.velocity = np.asarray(self.velocity, dtype=float)

    @property
    def speed(self) -> float:
        return float(np.linalg.norm(self.velocity))

    def effective_capability(self) -> CapabilityProfile:
        """Capability after fatigue degradation — what arrival-time code should use."""
        return self.capability.degraded(self.stamina)

    def moved_to(self, position, velocity=None) -> "PlayerState":
        """A copy at a new position (and optionally velocity)."""
        return replace(
            self,
            position=np.asarray(position, dtype=float),
            velocity=self.velocity if velocity is None else np.asarray(velocity, dtype=float),
        )


@dataclass
class BallState:
    """The ball at one instant."""

    position: np.ndarray
    velocity: np.ndarray = field(default_factory=lambda: vec(0.0, 0.0))
    height: float = 0.0
    carrier_id: int | None = None
    phase: BallPhase = BallPhase.ON_GROUND

    def __post_init__(self) -> None:
        self.position = np.asarray(self.position, dtype=float)
        self.velocity = np.asarray(self.velocity, dtype=float)

    @property
    def speed(self) -> float:
        return float(np.linalg.norm(self.velocity))


@dataclass(frozen=True)
class Waypoint:
    """A single "be here by then" requirement for one player.

    This is the unit that hard kinematic checks consume (D-014); a ``Play`` will later
    compose lists of these.

    ``deadline`` is seconds from the current instant. This is a deliberate
    simplification: design doc §3 requires waypoints triggered by *events* ("ball
    reaches point X", "defender crosses threshold Y") rather than clock time, and that
    representation is unresolved (Q-009). Expect this field to be **replaced**, not
    extended.
    """

    player_id: int
    target: np.ndarray
    deadline: float
    action: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "target", np.asarray(self.target, dtype=float))
