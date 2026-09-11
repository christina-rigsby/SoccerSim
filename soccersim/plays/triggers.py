"""Triggers — when a play step starts, and when to give up on it.

This resolves Q-009. Design doc §3 requires that a play's steps be "timed/triggered
relative to events (ball reaches point X, defender crosses threshold Y) rather than
fixed clock time", and M0's ``Waypoint.deadline`` was explicitly a placeholder to be
*replaced* rather than extended (D-014).

A trigger is a named, parameterised predicate over live state — the same registry
pattern as :mod:`soccersim.plays.anchors`, so a play remains data all the way down.
``ball_within`` is §3's "ball reaches point X"; ``opponent_within`` and ``role_beyond``
are "defender crosses threshold Y".

The same vocabulary serves three jobs, which is why it is worth having one of:

- **activation** — when a step begins;
- **completion** — when a step is judged done, where the action's default is not enough;
- **abort** — when to abandon the step, which is what makes D-002's "be willing to abort
  mid-play and reselect" expressible rather than aspirational.

``elapsed`` survives as a trigger, but as a *fallback* rather than the primary mechanism:
some steps genuinely are timed, and every step needs a timeout or a play whose trigger
never fires would hang forever.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar, Mapping

import numpy as np

from ..dashboard.measurements import pressure_on
from ..space.passing_lanes import assess_lane
from .anchors import Anchor, PlayContext, anchor_from_spec, shallow_fields


class TriggerError(ValueError):
    """A trigger is malformed, or cannot be evaluated in this state."""


@dataclass
class TriggerContext:
    """State a trigger is evaluated against.

    Carries the play's execution progress as well as the game state, because several
    triggers are about the play rather than the pitch: whether a prior step finished,
    how long this step has been waiting, whether a role has had the ball yet.
    """

    play: PlayContext
    clock: float
    #: When this step's dependencies were first satisfied. ``None`` while ineligible.
    eligible_since: float | None = None
    #: Keys of steps already complete.
    completed: frozenset[str] = frozenset()
    #: Roles that have been the ball carrier at some point during this play. Needed
    #: because "has played the ball" cannot be read from a single snapshot — a role that
    #: never had it and a role that has already released it look identical.
    held_ball: frozenset[str] = frozenset()
    play_started_at: float = 0.0

    @property
    def waiting(self) -> float:
        """Seconds since this step became eligible."""
        if self.eligible_since is None:
            return 0.0
        return max(0.0, self.clock - self.eligible_since)


@dataclass(frozen=True)
class Trigger:
    """Base class: a named, serialisable predicate over live state."""

    kind: ClassVar[str] = ""

    def evaluate(self, context: TriggerContext) -> bool:  # pragma: no cover - abstract
        raise NotImplementedError

    def to_spec(self) -> dict[str, Any]:
        """The JSON form, round-tripping exactly through :func:`trigger_from_spec`."""
        spec: dict[str, Any] = {"kind": self.kind}
        for key, value in shallow_fields(self).items():
            spec[key] = _serialise(value)
        return spec

    def describe(self) -> str:
        args = ", ".join(f"{k}={_brief(v)}" for k, v in shallow_fields(self).items())
        return f"{self.kind}({args})" if args else self.kind


def _serialise(value):
    if isinstance(value, (Anchor, Trigger)):
        return value.to_spec()
    if isinstance(value, (tuple, list)):
        return [_serialise(item) for item in value]
    return value


def _brief(value) -> str:
    if isinstance(value, (Anchor, Trigger)):
        return value.describe()
    if isinstance(value, (tuple, list)):
        return "[" + ", ".join(_brief(v) for v in value) + "]"
    return str(value)


@dataclass(frozen=True)
class Immediately(Trigger):
    """Fires as soon as the step is eligible. The opening steps of a play."""

    kind: ClassVar[str] = "immediately"

    def evaluate(self, context: TriggerContext) -> bool:
        return True


@dataclass(frozen=True)
class Elapsed(Trigger):
    """Fires once the step has been eligible for ``seconds``.

    A fallback, not the main mechanism (§3 wants event triggers) — but real plays do
    contain genuinely timed pauses, and it is the natural shape for a timeout.
    """

    kind: ClassVar[str] = "elapsed"
    seconds: float = 1.0

    def evaluate(self, context: TriggerContext) -> bool:
        return context.eligible_since is not None and context.waiting >= self.seconds


@dataclass(frozen=True)
class StepsDone(Trigger):
    """Fires when every named step has completed."""

    kind: ClassVar[str] = "steps_done"
    steps: tuple[str, ...] = ()

    def evaluate(self, context: TriggerContext) -> bool:
        return all(step in context.completed for step in self.steps)


@dataclass(frozen=True)
class BallWithin(Trigger):
    """§3's "ball reaches point X"."""

    kind: ClassVar[str] = "ball_within"
    anchor: Anchor | None = None
    metres: float = 3.0

    def evaluate(self, context: TriggerContext) -> bool:
        if self.anchor is None:
            raise TriggerError("ball_within needs an anchor")
        target = self.anchor.resolve(context.play)
        ball = np.asarray(context.play.state.ball.position, dtype=float)
        return float(np.linalg.norm(ball - target)) <= self.metres


@dataclass(frozen=True)
class BallPlayedBy(Trigger):
    """Fires once a role has had the ball and released it.

    Needs the play's history, not just the snapshot: a role that never received the ball
    and one that has already passed it are indistinguishable from a single frame.
    """

    kind: ClassVar[str] = "ball_played_by"
    role: str = ""

    def evaluate(self, context: TriggerContext) -> bool:
        if self.role not in context.held_ball:
            return False
        carrier = context.play.state.ball.carrier_id
        return carrier != context.play.assignment.get(self.role)


@dataclass(frozen=True)
class RoleWithin(Trigger):
    """A role's player has arrived within ``metres`` of an anchor."""

    kind: ClassVar[str] = "role_within"
    role: str = ""
    anchor: Anchor | None = None
    metres: float = 2.5

    def evaluate(self, context: TriggerContext) -> bool:
        if self.anchor is None:
            raise TriggerError("role_within needs an anchor")
        position = context.play.player(self.role).position
        target = self.anchor.resolve(context.play)
        return float(np.linalg.norm(np.asarray(position, dtype=float) - target)) <= self.metres


@dataclass(frozen=True)
class RoleBeyond(Trigger):
    """A role's player has advanced past an anchor, in the attacking direction.

    §3's "defender crosses threshold Y", applied to our own runners: this is how an
    overlap knows the full-back has actually got outside the winger.
    """

    kind: ClassVar[str] = "role_beyond"
    role: str = ""
    anchor: Anchor | None = None
    margin: float = 0.0

    def evaluate(self, context: TriggerContext) -> bool:
        if self.anchor is None:
            raise TriggerError("role_beyond needs an anchor")
        direction = context.play.attacking_direction
        position = context.play.player(self.role).position
        target = self.anchor.resolve(context.play)
        return direction * (float(position[0]) - float(target[0])) >= self.margin


@dataclass(frozen=True)
class OpponentWithin(Trigger):
    """An opponent has closed to within ``metres`` of a role.

    The other half of §3's "defender crosses threshold Y", and the natural abort
    condition for a step that depends on being unmarked.
    """

    kind: ClassVar[str] = "opponent_within"
    role: str = ""
    metres: float = 5.0

    def evaluate(self, context: TriggerContext) -> bool:
        play = context.play
        position = np.asarray(play.player(self.role).position, dtype=float)
        opponents = play.state.opponents_of(play.team).available()
        if not opponents:
            return False
        distances = [
            float(np.linalg.norm(np.asarray(o.position, dtype=float) - position))
            for o in opponents
        ]
        return min(distances) <= self.metres


@dataclass(frozen=True)
class LaneOpen(Trigger):
    """The passing lane between two anchors is open.

    Reuses M0's lane assessment, so the trigger and the space layer cannot disagree
    about whether a pass is on.
    """

    kind: ClassVar[str] = "lane_open"
    origin: Anchor | None = None
    target: Anchor | None = None

    def evaluate(self, context: TriggerContext) -> bool:
        if self.origin is None or self.target is None:
            raise TriggerError("lane_open needs origin and target anchors")
        play = context.play
        return assess_lane(
            play.state,
            self.origin.resolve(play),
            self.target.resolve(play),
            passing_team=play.team,
        ).is_open


@dataclass(frozen=True)
class ControlAbove(Trigger):
    """We control the space at an anchor above a threshold."""

    kind: ClassVar[str] = "control_above"
    anchor: Anchor | None = None
    threshold: float = 0.5

    def evaluate(self, context: TriggerContext) -> bool:
        if self.anchor is None:
            raise TriggerError("control_above needs an anchor")
        play = context.play
        return play.control().at(self.anchor.resolve(play)) >= self.threshold


@dataclass(frozen=True)
class PressureAbove(Trigger):
    """A role is under pressure above an intensity threshold.

    Primarily an abort condition: a play built on a free player stops making sense the
    moment they are closed down.
    """

    kind: ClassVar[str] = "pressure_above"
    role: str = ""
    intensity: float = 1.0

    def evaluate(self, context: TriggerContext) -> bool:
        play = context.play
        player = play.player(self.role)
        return pressure_on(play.state, player.player_id).intensity >= self.intensity


@dataclass(frozen=True)
class AllOf(Trigger):
    kind: ClassVar[str] = "all_of"
    of: tuple[Trigger, ...] = ()

    def evaluate(self, context: TriggerContext) -> bool:
        return all(trigger.evaluate(context) for trigger in self.of)


@dataclass(frozen=True)
class AnyOf(Trigger):
    kind: ClassVar[str] = "any_of"
    of: tuple[Trigger, ...] = ()

    def evaluate(self, context: TriggerContext) -> bool:
        return any(trigger.evaluate(context) for trigger in self.of)


@dataclass(frozen=True)
class Not(Trigger):
    kind: ClassVar[str] = "not"
    of: Trigger | None = None

    def evaluate(self, context: TriggerContext) -> bool:
        if self.of is None:
            raise TriggerError("not needs an inner trigger")
        return not self.of.evaluate(context)


TRIGGER_KINDS: dict[str, type[Trigger]] = {
    cls.kind: cls
    for cls in (
        Immediately, Elapsed, StepsDone, BallWithin, BallPlayedBy, RoleWithin,
        RoleBeyond, OpponentWithin, LaneOpen, ControlAbove, PressureAbove,
        AllOf, AnyOf, Not,
    )
}

#: Parameters that hold a nested anchor, and those that hold nested triggers.
_ANCHOR_FIELDS = frozenset({"anchor", "origin", "target"})
_TRIGGER_LIST_FIELDS = frozenset({"of"})


def trigger_from_spec(spec: Mapping[str, Any]) -> Trigger:
    """Build a trigger from its JSON form, validating strictly and recursing."""
    if not isinstance(spec, Mapping):
        raise TriggerError(f"trigger must be an object, got {type(spec).__name__}")
    kind = spec.get("kind")
    if kind not in TRIGGER_KINDS:
        raise TriggerError(
            f"unknown trigger kind {kind!r}; known kinds are "
            f"{', '.join(sorted(TRIGGER_KINDS))}"
        )
    cls = TRIGGER_KINDS[kind]
    allowed = set(cls.__dataclass_fields__)
    given = {k: v for k, v in spec.items() if k != "kind"}
    unknown = sorted(set(given) - allowed)
    if unknown:
        raise TriggerError(
            f"trigger {kind!r}: unknown parameter(s) {', '.join(unknown)}. "
            f"Allowed: {', '.join(sorted(allowed)) or '(none)'}."
        )

    for key in list(given):
        if key in _ANCHOR_FIELDS:
            given[key] = anchor_from_spec(given[key])
        elif key in _TRIGGER_LIST_FIELDS:
            value = given[key]
            if cls is Not:
                given[key] = trigger_from_spec(value)
            else:
                if not isinstance(value, (list, tuple)) or not value:
                    raise TriggerError(f"trigger {kind!r}: 'of' must be a non-empty list")
                given[key] = tuple(trigger_from_spec(item) for item in value)
        elif key == "steps":
            given[key] = tuple(given[key])

    try:
        return cls(**given)
    except TypeError as error:
        raise TriggerError(f"trigger {kind!r}: {error}") from None
