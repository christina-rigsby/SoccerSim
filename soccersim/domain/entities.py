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

from .attributes import Attributes, Foot
from .pitch import vec


class Team(Enum):
    HOME = "home"
    AWAY = "away"

    @property
    def other(self) -> "Team":
        return Team.AWAY if self is Team.HOME else Team.HOME


class PositionalRole(Enum):
    """Where a player lines up — a formation slot, not a job within a play.

    This is emphatically *not* the same concept as
    :class:`~soccersim.domain.roles.PlayRole`. "RB" is where you start; "overlap runner"
    is what a particular play needs someone to do, and a RB, RM or even RCM might fill
    it. Conflating the two is what the design doc's §4 ``RoleRequirement`` avoids, and
    keeping them separate is why plays can generalise across formations (D-018).

    An enum rather than a free string because rosters are hand-edited JSON, where a
    typo'd slot should fail loudly at load time rather than silently match nothing.
    """

    GK = "GK"
    LB = "LB"
    LCB = "LCB"
    CB = "CB"
    RCB = "RCB"
    RB = "RB"
    CDM = "CDM"
    LCM = "LCM"
    CM = "CM"
    RCM = "RCM"
    LM = "LM"
    RM = "RM"
    LW = "LW"
    RW = "RW"
    CF = "CF"
    ST = "ST"
    UNKNOWN = "unknown"

    @property
    def is_goalkeeper(self) -> bool:
        return self is PositionalRole.GK

    @property
    def flank(self) -> str:
        """``"left"``, ``"right"`` or ``"central"`` — the slot's side of the pitch.

        Read by roles whose quality depends on which foot the flank leaves available
        (an inverted winger is the obvious case). Side is nominal, not
        attacking-direction-relative.
        """
        if self.value.startswith("L"):
            return "left"
        if self.value.startswith("R"):
            return "right"
        return "central"


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

    Splits into three kinds of field, which change on very different timescales:

    - **Per-instant**: ``position``, ``velocity``, ``stamina``, ``available``.
    - **Roster-supplied identity**: ``positional_role``, ``capability``,
      ``attributes``, ``foot``, ``practised_roles`` — loaded from a roster file
      (:mod:`soccersim.domain.roster`) and constant through a match.
    - **Derived**: nothing stored; fit, arrival times and the rest are computed.

    ``attributes`` is optional because only *our own* players have authored ratings.
    An opponent's attributes have to be inferred from observed play (Q-008), so away
    players legitimately carry ``None`` until the dashboard can estimate them — that is
    a modelling fact, not missing data (D-021).
    """

    player_id: int
    team: Team
    position: np.ndarray
    velocity: np.ndarray = field(default_factory=lambda: vec(0.0, 0.0))
    positional_role: PositionalRole = PositionalRole.UNKNOWN
    capability: CapabilityProfile = field(default_factory=CapabilityProfile)
    stamina: float = 1.0
    available: bool = True  # False when injured, carded off, or otherwise out
    name: str = ""
    shirt: int | None = None
    attributes: Attributes | None = None
    foot: Foot = Foot.RIGHT
    practised_roles: frozenset[str] = frozenset()
    """Play-role keys this player has actually rehearsed.

    Read by §5's ``role_familiarity`` soft constraint, which "penalise[s] assigning a
    player to a role/play they haven't practised, if tracked". Tracking it needs an
    explicit set; it cannot be derived from attributes, which is why fit is computed
    *and* familiarity is recorded (D-019).
    """

    def __post_init__(self) -> None:
        self.position = np.asarray(self.position, dtype=float)
        self.velocity = np.asarray(self.velocity, dtype=float)
        self.practised_roles = frozenset(self.practised_roles)

    @property
    def speed(self) -> float:
        return float(np.linalg.norm(self.velocity))

    @property
    def label(self) -> str:
        """Shirt-and-name for display, falling back to the id."""
        shirt = self.shirt if self.shirt is not None else self.player_id
        return f"#{shirt} {self.name}".strip() if self.name else f"#{shirt}"

    def require_attributes(self) -> Attributes:
        """``attributes``, or a clear error explaining why they might be absent."""
        if self.attributes is None:
            raise ValueError(
                f"player {self.label} ({self.team.value}) has no attributes. Our own "
                "players get them from a roster file (soccersim.domain.roster); "
                "opponents' attributes must be inferred from observed play and are "
                "not available yet (Q-008)."
            )
        return self.attributes

    def has_practised(self, role_key: str) -> bool:
        return role_key in self.practised_roles

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
