"""Spatial anchors — how a play says "here" without saying a coordinate.

This is the mechanism behind D-003. A waypoint target is not ``(x, y)``; it is a named,
parameterised *function of the live game state*. Design doc §3 names four, and all four
are implemented here on top of machinery M0 already built:

===================================================  =========================
"point of maximum pitch-control gain along the flank" :class:`MaxControl`
"midpoint of the gap between CB and fullback"         :class:`LineGap`
"N meters behind the last defender's line, in the channel" :class:`BehindLine`
"edge of the nearest defender's cover shadow"         :class:`CoverShadowEdge`
===================================================  =========================

Because the geometry is recomputed every epoch, one play generalises across opponent
formations instead of needing a variant per shape.

**Flanks are team-relative.** A parameter of ``"right"`` means the attacking team's
right, which is a different side of the pitch depending on which way they are playing.
The pitch's own channel naming is nominal and direction-agnostic (M0's
``Pitch.channel``: left is negative ``y``), so :func:`flank_sign` does the conversion in
one place. Getting this wrong would mirror every play, which is the subtle failure Q-011
exists to guard against.

**Anchors are not clamped to the pitch.** An anchor that resolves out of bounds means the
play does not fit this situation — a run 8 m behind a line already on its own goal line
has nowhere to go — and the ``pitch_bounds`` hard constraint reports that honestly.
Silently clamping would turn an infeasible play into a subtly different feasible one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar, Mapping

import numpy as np

from ..dashboard.measurements import DefensiveLine, defensive_line
from ..domain.entities import PlayerState, Team
from ..domain.pitch import Pitch, vec
from ..domain.state import GameState
from ..space.grid import PitchGrid
from ..space.passing_lanes import BODY_RADIUS
from ..space.pitch_control import ControlField, control_field

FLANKS = ("left", "left_half", "centre", "right_half", "right")
THIRDS = ("defensive", "middle", "final")


class AnchorError(ValueError):
    """An anchor is malformed, or cannot be resolved in this state."""


def shallow_fields(obj) -> dict[str, Any]:
    """Field name -> value, without recursing into nested dataclasses.

    ``dataclasses.asdict`` recurses, which destroys nested anchors and triggers on the
    way to JSON. Everything that serialises or describes a spec tree goes through here.
    """
    from dataclasses import fields

    return {f.name: getattr(obj, f.name) for f in fields(obj)}


def flank_sign(flank: str, attacking_direction: int) -> float:
    """Lateral sign for a team-relative flank.

    The pitch names ``left`` as negative ``y`` irrespective of direction, and the
    fixtures follow that (home attacks ``+x`` with its left-back at negative ``y``). By
    mirror symmetry a team attacking the other way has its left at positive ``y``, so
    the team's left is ``-attacking_direction`` and its right ``+attacking_direction``.
    """
    if flank not in FLANKS:
        raise AnchorError(f"unknown flank {flank!r}; expected one of {', '.join(FLANKS)}")
    if flank == "centre":
        return 0.0
    return float(np.sign(attacking_direction)) * (
        -1.0 if flank.startswith("left") else 1.0
    )


def channel_centre_y(flank: str, pitch: Pitch, attacking_direction: int) -> float:
    """Lateral centre of a team-relative channel, in pitch coordinates.

    Channel boundaries follow ``Pitch.channel``: the wide channels sit outside the
    penalty-box overhang, the half-spaces between the box edge and the goal-area edge.
    """
    sign = flank_sign(flank, attacking_direction)
    if flank == "centre":
        return 0.0
    wide_edge = pitch.penalty_box_width / 2.0
    half_edge = pitch.goal_area_width / 2.0
    magnitude = (
        (wide_edge + pitch.half_width) / 2.0
        if flank in ("left", "right")
        else (wide_edge + half_edge) / 2.0
    )
    return sign * magnitude


@dataclass
class PlayContext:
    """Everything an anchor or trigger needs, with geometry computed at most once.

    A play resolves many anchors per epoch and several of them want the control field or
    the opponent's defensive line. Recomputing a full-pitch control field per anchor
    would dominate the per-epoch budget (Q-012), so both are cached here for the life of
    the context — which is one snapshot.
    """

    state: GameState
    team: Team
    #: Play-role key -> assigned player id. Built by M1's assignment solve; supplied by
    #: hand or by test fixtures until then.
    assignment: Mapping[str, int] = field(default_factory=dict)
    grid_resolution: float = 2.0
    _control: ControlField | None = field(default=None, repr=False)
    _line: DefensiveLine | None = field(default=None, repr=False)
    _line_computed: bool = field(default=False, repr=False)

    @property
    def pitch(self) -> Pitch:
        return self.state.pitch

    @property
    def attacking_direction(self) -> int:
        return self.state.attacking_direction(self.team)

    def player(self, role_key: str) -> PlayerState:
        """The player filling ``role_key``."""
        try:
            player_id = self.assignment[role_key]
        except KeyError:
            raise AnchorError(
                f"role {role_key!r} is not assigned; assigned roles are "
                f"{sorted(self.assignment)}"
            ) from None
        return self.state.player(player_id)

    def control(self) -> ControlField:
        if self._control is None:
            self._control = control_field(
                self.state, self.team, PitchGrid(self.pitch, self.grid_resolution)
            )
        return self._control

    def opponent_line_x(self, count: int = 4) -> float:
        """Pitch ``x`` of the opponent's defensive line.

        :attr:`DefensiveLine.height` is stored as *the opponent's* attacking-relative
        progress, so converting it back to a pitch coordinate needs **their** direction,
        which is the negation of ours. Doing that conversion here rather than at each
        use site is deliberate: getting the sign wrong resolves anchors into our own half,
        which is the exact class of mirroring bug Q-011 exists to catch.
        """
        return -self.attacking_direction * self.opponent_line(count).height

    def opponent_line(self, count: int = 4) -> DefensiveLine:
        if not self._line_computed:
            self._line = defensive_line(self.state.opponents_of(self.team), count)
            self._line_computed = True
        if self._line is None:
            raise AnchorError(
                "the opponent has too few available outfield players to define a "
                "defensive line"
            )
        return self._line


# ---------------------------------------------------------------------------
# Anchor kinds
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Anchor:
    """Base class: a named, serialisable resolver from game state to a point."""

    kind: ClassVar[str] = ""
    params: ClassVar[frozenset[str]] = frozenset()

    def resolve(self, context: PlayContext) -> np.ndarray:  # pragma: no cover - abstract
        raise NotImplementedError

    def to_spec(self) -> dict[str, Any]:
        """The JSON form, round-tripping exactly through :func:`anchor_from_spec`.

        Uses shallow field access rather than ``dataclasses.asdict``, which recurses
        into nested dataclasses and would flatten a nested anchor into a plain dict —
        losing its ``kind`` (a ``ClassVar``, so absent from the dict) and silently
        breaking the round trip that makes plays-as-data work.
        """
        spec: dict[str, Any] = {"kind": self.kind}
        for key, value in shallow_fields(self).items():
            spec[key] = value.to_spec() if isinstance(value, Anchor) else value
        return spec

    def describe(self) -> str:
        args = ", ".join(
            f"{k}={v.describe() if isinstance(v, Anchor) else v}"
            for k, v in shallow_fields(self).items()
        )
        return f"{self.kind}({args})" if args else self.kind


@dataclass(frozen=True)
class PlayerAnchor(Anchor):
    """Where the player filling a role currently is."""

    kind: ClassVar[str] = "player"
    role: str

    def resolve(self, context: PlayContext) -> np.ndarray:
        return np.array(context.player(self.role).position, dtype=float)


@dataclass(frozen=True)
class BallAnchor(Anchor):
    """Where the ball is."""

    kind: ClassVar[str] = "ball"

    def resolve(self, context: PlayContext) -> np.ndarray:
        return np.array(context.state.ball.position, dtype=float)


@dataclass(frozen=True)
class GoalAnchor(Anchor):
    """The centre of the goal being attacked."""

    kind: ClassVar[str] = "goal"

    def resolve(self, context: PlayContext) -> np.ndarray:
        return context.pitch.goal_centre(context.attacking_direction)


@dataclass(frozen=True)
class MaxControl(Anchor):
    """Point of maximum pitch-control gain, optionally restricted to a zone.

    §3's "point of maximum pitch-control gain along the flank". The restriction matters:
    unrestricted, the most-controlled point on the pitch is usually next to your own
    goalkeeper, which is uncontested and worthless.
    """

    kind: ClassVar[str] = "max_control"
    third: str | None = None
    flank: str | None = None

    def __post_init__(self) -> None:
        if self.third is not None and self.third not in THIRDS:
            raise AnchorError(
                f"unknown third {self.third!r}; expected one of {', '.join(THIRDS)}"
            )
        if self.flank is not None:
            flank_sign(self.flank, 1)  # validates the name

    def resolve(self, context: PlayContext) -> np.ndarray:
        control = context.control()
        points = control.grid.points()
        mask = np.ones(points.shape[:-1], dtype=bool)
        direction = context.attacking_direction

        if self.third is not None:
            progress = direction * points[..., 0]
            cut = context.pitch.half_length / 3.0
            if self.third == "defensive":
                mask &= progress < -cut
            elif self.third == "final":
                mask &= progress > cut
            else:
                mask &= (progress >= -cut) & (progress <= cut)

        if self.flank is not None:
            sign = flank_sign(self.flank, direction)
            wide_edge = context.pitch.penalty_box_width / 2.0
            half_edge = context.pitch.goal_area_width / 2.0
            ys = points[..., 1]
            if self.flank == "centre":
                mask &= np.abs(ys) <= half_edge
            elif self.flank in ("left", "right"):
                mask &= sign * ys > wide_edge
            else:
                mask &= (sign * ys > half_edge) & (sign * ys <= wide_edge)

        if not mask.any():
            raise AnchorError(
                f"no grid cells match third={self.third!r} flank={self.flank!r}"
            )
        return control.best_point(mask)


@dataclass(frozen=True)
class LineGap(Anchor):
    """Midpoint of a gap in the opponent's defensive line, pushed up to the line.

    §3's "midpoint of the gap between CB and fullback" — found by *measuring* which pair
    is actually widest apart rather than assuming which slots are adjacent, so it works
    against a back three, a back five, or a line that has been pulled out of shape.
    """

    kind: ClassVar[str] = "line_gap"
    #: Which gap by width rank: 0 is the widest.
    rank: int = 0
    #: Metres beyond the line to place the point. 0 sits on the line itself.
    metres_beyond: float = 0.0
    #: Restrict to gaps whose midpoint is on this team-relative side. A right-sided
    #: underlap wants a gap on the right, not the widest gap anywhere on the pitch.
    flank: str | None = None

    def __post_init__(self) -> None:
        if self.flank is not None:
            flank_sign(self.flank, 1)

    def resolve(self, context: PlayContext) -> np.ndarray:
        line = context.opponent_line()
        if not line.gaps:
            raise AnchorError("the opponent's defensive line has no measurable gaps")
        if self.rank >= len(line.gaps):
            raise AnchorError(
                f"gap rank {self.rank} requested but the line has only "
                f"{len(line.gaps)} gaps"
            )

        state = context.state
        midpoints = [
            (
                float(state.player(line.player_ids[i]).position[1])
                + float(state.player(line.player_ids[i + 1]).position[1])
            )
            / 2.0
            for i in range(len(line.gaps))
        ]
        candidates = list(range(len(line.gaps)))
        if self.flank is not None:
            sign = flank_sign(self.flank, context.attacking_direction)
            candidates = [i for i in candidates if sign * midpoints[i] > 0] or candidates
        order = sorted(candidates, key=lambda i: line.gaps[i], reverse=True)
        if self.rank >= len(order):
            raise AnchorError(
                f"gap rank {self.rank} requested but only {len(order)} gaps match "
                f"flank={self.flank!r}"
            )
        index = int(order[self.rank])
        state = context.state
        left = state.player(line.player_ids[index]).position
        right = state.player(line.player_ids[index + 1]).position
        midpoint_y = (float(left[1]) + float(right[1])) / 2.0
        # `metres_beyond` is measured in our attacking direction, so a positive value
        # sits past the line and a negative one in front of it.
        x = context.opponent_line_x() + context.attacking_direction * self.metres_beyond
        return vec(x, midpoint_y)


@dataclass(frozen=True)
class BehindLine(Anchor):
    """A point beyond the opponent's last-defender line, in a team-relative channel.

    §3's "N meters behind the last defender's line, in the channel". Deliberately
    unclamped: if the line is already within ``metres`` of its own goal line there is no
    space behind it, and the resulting out-of-bounds point makes the play infeasible,
    which is the correct answer rather than an error to paper over.
    """

    kind: ClassVar[str] = "behind_line"
    metres: float = 6.0
    flank: str = "centre"
    #: How many defenders define the line. 2 approximates the offside line.
    line_count: int = 4

    def __post_init__(self) -> None:
        flank_sign(self.flank, 1)
        if self.metres < 0:
            raise AnchorError("behind_line metres must be non-negative")

    def resolve(self, context: PlayContext) -> np.ndarray:
        direction = context.attacking_direction
        x = context.opponent_line_x(self.line_count) + direction * self.metres
        return vec(x, channel_centre_y(self.flank, context.pitch, direction))


@dataclass(frozen=True)
class CoverShadowEdge(Anchor):
    """Just outside the cover shadow of the defender nearest the ball.

    §3's "edge of the nearest defender's cover shadow" — the closest place a pass can
    actually reach. Both edges of the wedge qualify geometrically; this picks the side
    we control better, which is the side worth receiving on.
    """

    kind: ClassVar[str] = "cover_shadow_edge"
    #: Metres beyond the defender along the ball-to-defender axis.
    depth: float = 12.0
    #: Extra clearance outside the shadow boundary.
    margin: float = 1.5

    def resolve(self, context: PlayContext) -> np.ndarray:
        state = context.state
        ball = np.array(state.ball.position, dtype=float)
        opponents = state.opponents_of(context.team).available()
        if not opponents:
            raise AnchorError("no available opponent to cast a cover shadow")

        nearest = min(
            opponents, key=lambda p: float(np.linalg.norm(p.position - ball))
        )
        offset = np.array(nearest.position, dtype=float) - ball
        distance = float(np.linalg.norm(offset))
        if distance < 1e-6:
            raise AnchorError("the nearest opponent is standing on the ball")

        axis = offset / distance
        normal = np.array([-axis[1], axis[0]])
        half_angle = np.arcsin(min(1.0, BODY_RADIUS / max(distance, BODY_RADIUS)))
        total = distance + self.depth
        spread = float(np.tan(half_angle) * total) + self.margin
        base = ball + axis * total

        control = context.control()
        candidates = (base + normal * spread, base - normal * spread)
        return max(candidates, key=control.at)


@dataclass(frozen=True)
class ChannelDepth(Anchor):
    """A point at a given channel and a given fraction of the way to the goal.

    The workhorse for "hold width here" and "occupy this space", expressed relative to
    the attacking direction so it mirrors for free. ``progress`` of 0 is the halfway
    line and 1 the opponent's goal line.
    """

    kind: ClassVar[str] = "channel_depth"
    flank: str = "centre"
    progress: float = 0.5

    def __post_init__(self) -> None:
        flank_sign(self.flank, 1)

    def resolve(self, context: PlayContext) -> np.ndarray:
        direction = context.attacking_direction
        x = direction * self.progress * context.pitch.half_length
        return vec(x, channel_centre_y(self.flank, context.pitch, direction))


@dataclass(frozen=True)
class BoxTarget(Anchor):
    """A delivery target inside the penalty box, relative to the ball's side.

    Near and far post are defined relative to *where the ball is*, which is what a cross
    target actually means — so the same anchor serves a cross from either flank without
    a mirrored variant.

    By default the point is **pulled back to stay onside**: never beyond the second-last
    defender. This is not a detail. A striker attacking a cross stays onside by
    definition, so a fixed six-yard-box target is offside against any deep block — and
    since offside is judged at the moment of the pass, every cross in the library aborted
    until this was line-aware. Set ``onside=False`` for a dead-ball restart, where
    offside does not apply from the restart itself.
    """

    kind: ClassVar[str] = "box_target"
    #: ``"near"``, ``"far"``, ``"spot"`` (penalty spot) or ``"edge"`` (box edge, central).
    spot: str = "near"
    #: Clamp the depth to stay level with or behind the second-last defender.
    onside: bool = True
    #: Clearance kept in front of the offside line when clamping.
    onside_margin: float = 0.8

    def __post_init__(self) -> None:
        if self.spot not in ("near", "far", "spot", "edge"):
            raise AnchorError(
                f"unknown box target {self.spot!r}; expected near, far, spot or edge"
            )

    def resolve(self, context: PlayContext) -> np.ndarray:
        pitch = context.pitch
        direction = context.attacking_direction
        ball_y = float(context.state.ball.position[1])
        post = pitch.goal_area_width / 2.0  # six-yard box: the usual post reference

        if self.spot == "spot":
            depth, lateral = pitch.penalty_spot_distance, 0.0
        elif self.spot == "edge":
            depth, lateral = pitch.penalty_box_depth, 0.0
        else:
            side = 1.0 if ball_y >= 0 else -1.0
            if self.spot == "far":
                side = -side
            depth, lateral = pitch.goal_area_depth + 1.0, side * post

        progress = pitch.half_length - depth
        if self.onside:
            try:
                line_progress = direction * context.opponent_line_x(2)
            except AnchorError:
                line_progress = progress
            progress = min(progress, line_progress - self.onside_margin)
        return vec(direction * progress, lateral)


@dataclass(frozen=True)
class OpponentAnchor(Anchor):
    """Where a particular opponent is.

    Defensive plays need this: §3's press plays act *on* a player, not on a point, and
    ``press``/``mark_man``/``jockey`` are meaningless without one. Selection is by live
    predicate rather than by id so a press play does not need rewriting when a different
    opponent picks the ball up.
    """

    kind: ClassVar[str] = "opponent"
    #: ``"carrier"``, ``"nearest_to_ball"``, or ``"nearest_to_role"``.
    which: str = "carrier"
    #: Required when ``which`` is ``"nearest_to_role"``.
    role: str | None = None

    def __post_init__(self) -> None:
        if self.which not in ("carrier", "nearest_to_ball", "nearest_to_role"):
            raise AnchorError(
                f"unknown opponent selector {self.which!r}; expected carrier, "
                "nearest_to_ball or nearest_to_role"
            )
        if self.which == "nearest_to_role" and not self.role:
            raise AnchorError("opponent(which='nearest_to_role') needs a role")

    def resolve(self, context: PlayContext) -> np.ndarray:
        return np.array(self.player(context).position, dtype=float)

    def player(self, context: PlayContext) -> PlayerState:
        """The selected opponent, so defensive actions can name an id, not just a point."""
        state = context.state
        opponents = state.opponents_of(context.team).available()
        if not opponents:
            raise AnchorError("no available opponent to anchor to")

        if self.which == "carrier":
            carrier = state.ball.carrier_id
            if carrier is None:
                raise AnchorError(
                    "opponent(which='carrier') resolved while nobody has the ball"
                )
            if state.team_of(carrier) is context.team:
                raise AnchorError(
                    "opponent(which='carrier') resolved while our own team has the ball"
                )
            return state.player(carrier)

        reference = (
            np.asarray(state.ball.position, dtype=float)
            if self.which == "nearest_to_ball"
            else np.asarray(context.player(self.role).position, dtype=float)
        )
        return min(
            opponents,
            key=lambda o: float(np.linalg.norm(np.asarray(o.position, dtype=float) - reference)),
        )


@dataclass(frozen=True)
class Offset(Anchor):
    """Another anchor shifted in attacking-relative metres.

    ``forward`` is toward the opponent's goal and ``lateral`` toward the team's right,
    both flipping automatically with attacking direction. Composable, so a play can say
    "two metres behind the overlap runner" without a bespoke anchor kind.
    """

    kind: ClassVar[str] = "offset"
    base: Anchor = field(default_factory=BallAnchor)
    forward: float = 0.0
    lateral: float = 0.0

    def resolve(self, context: PlayContext) -> np.ndarray:
        direction = context.attacking_direction
        origin = self.base.resolve(context)
        return origin + vec(direction * self.forward, direction * self.lateral)


ANCHOR_KINDS: dict[str, type[Anchor]] = {
    cls.kind: cls
    for cls in (
        PlayerAnchor, BallAnchor, GoalAnchor, MaxControl, LineGap, BehindLine,
        CoverShadowEdge, ChannelDepth, BoxTarget, OpponentAnchor, Offset,
    )
}


def anchor_from_spec(spec: Mapping[str, Any]) -> Anchor:
    """Build an anchor from its JSON form, validating strictly.

    Nested anchors (``offset``'s ``base``) recurse, so an anchor tree is data all the
    way down.
    """
    if not isinstance(spec, Mapping):
        raise AnchorError(f"anchor must be an object, got {type(spec).__name__}")
    kind = spec.get("kind")
    if kind not in ANCHOR_KINDS:
        raise AnchorError(
            f"unknown anchor kind {kind!r}; known kinds are "
            f"{', '.join(sorted(ANCHOR_KINDS))}"
        )
    cls = ANCHOR_KINDS[kind]
    allowed = {f for f in cls.__dataclass_fields__}
    given = {k: v for k, v in spec.items() if k != "kind"}
    unknown = sorted(set(given) - allowed)
    if unknown:
        raise AnchorError(
            f"anchor {kind!r}: unknown parameter(s) {', '.join(unknown)}. "
            f"Allowed: {', '.join(sorted(allowed)) or '(none)'}."
        )
    if "base" in given:
        given["base"] = anchor_from_spec(given["base"])
    try:
        return cls(**given)
    except TypeError as error:
        raise AnchorError(f"anchor {kind!r}: {error}") from None
