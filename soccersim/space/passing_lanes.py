"""Passing-lane assessment and defender cover shadows.

A lane is judged by racing the ball against the defence: sample points along the
straight line from passer to target, and at each one compare how long the ball takes to
arrive against the soonest any defender could be there. The tightest margin over the
whole lane decides whether it is open.

**Ball flight is modelled as constant speed along a straight 2-D segment** (D-016,
provisional; see Q-007). That is wrong, not merely imprecise, for lofted and through
balls — a chipped pass travels *over* a defender, so a 2-D occlusion test cannot
represent it. Design doc §3 distinguishes ``ground|lofted|through``, and this module
currently only models the ground case honestly.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..domain.entities import PlayerState, Team
from ..domain.state import GameState
from ..kinematics import player_time_to_point

#: Firm ground pass, m/s. Real passes decelerate (Q-007).
DEFAULT_PASS_SPEED = 15.0

#: A defender needs to beat the ball by more than this to count as blocking the lane.
#: Arriving simultaneously is a contest, not an interception.
DEFAULT_SAFETY_MARGIN = 0.0

#: Samples within this distance of the passer are skipped — the passer's own body
#: occupies that space and a defender standing on top of them is a pressure problem,
#: not a lane-occlusion problem.
MIN_SAMPLE_DISTANCE = 1.0

#: Effective radius of a player's body for occlusion purposes, in metres.
BODY_RADIUS = 0.4


@dataclass
class LaneAssessment:
    """The outcome of racing the ball against the defence along one lane."""

    origin: np.ndarray
    target: np.ndarray
    is_open: bool
    #: Seconds by which the defence beats the ball at the tightest point on the lane.
    #: Negative means the ball wins everywhere — a comfortably open lane.
    tightest_margin: float
    #: Ids of defenders who beat the ball somewhere along the lane.
    blockers: tuple[int, ...]
    #: Point on the lane where the defence is closest to winning the race.
    tightest_point: np.ndarray

    @property
    def length(self) -> float:
        return float(np.linalg.norm(self.target - self.origin))


def _lane_samples(origin: np.ndarray, target: np.ndarray, spacing: float) -> np.ndarray:
    """Points along the lane, skipping the stretch closest to the passer."""
    total = float(np.linalg.norm(target - origin))
    if total <= MIN_SAMPLE_DISTANCE:
        return target.reshape(1, 2)
    n = max(2, int(np.ceil((total - MIN_SAMPLE_DISTANCE) / spacing)) + 1)
    fractions = np.linspace(MIN_SAMPLE_DISTANCE / total, 1.0, n)
    return origin + fractions[:, None] * (target - origin)


def assess_lane(
    state: GameState,
    origin,
    target,
    passing_team: Team = Team.HOME,
    pass_speed: float = DEFAULT_PASS_SPEED,
    safety_margin: float = DEFAULT_SAFETY_MARGIN,
    sample_spacing: float = 1.0,
) -> LaneAssessment:
    """Assess the lane from ``origin`` to ``target`` for ``passing_team``.

    ``origin`` is a point rather than a player so that hypothetical passes (from where
    the ball *will* be) can be evaluated as easily as actual ones.
    """
    o = np.asarray(origin, dtype=float)
    t = np.asarray(target, dtype=float)
    samples = _lane_samples(o, t, sample_spacing)

    ball_time = np.linalg.norm(samples - o, axis=1) / pass_speed

    defenders = state.opponents_of(passing_team).available()
    if not defenders:
        return LaneAssessment(
            origin=o,
            target=t,
            is_open=True,
            tightest_margin=float("-inf"),
            blockers=(),
            tightest_point=t,
        )

    # (n_defenders, n_samples): how much sooner each defender arrives than the ball.
    margins = np.stack(
        [np.asarray(player_time_to_point(d, samples)) - ball_time for d in defenders]
    )
    margins = -margins  # positive => defender beats the ball

    per_defender_best = margins.max(axis=1)
    blockers = tuple(
        int(d.player_id)
        for d, m in zip(defenders, per_defender_best)
        if m > safety_margin
    )

    flat_best = int(np.argmax(margins))
    _, tightest_index = np.unravel_index(flat_best, margins.shape)
    tightest_margin = float(margins.max())

    return LaneAssessment(
        origin=o,
        target=t,
        is_open=tightest_margin <= safety_margin,
        tightest_margin=tightest_margin,
        blockers=blockers,
        tightest_point=samples[int(tightest_index)],
    )


def assess_lane_to_player(
    state: GameState,
    origin,
    receiver: PlayerState,
    **kwargs,
) -> LaneAssessment:
    """:func:`assess_lane` with a teammate's current position as the target."""
    kwargs.setdefault("passing_team", receiver.team)
    return assess_lane(state, origin, receiver.position, **kwargs)


def open_lanes(
    state: GameState,
    origin,
    passing_team: Team = Team.HOME,
    exclude: tuple[int, ...] = (),
    **kwargs,
) -> list[tuple[PlayerState, LaneAssessment]]:
    """Assess lanes from ``origin`` to every available teammate.

    Returned sorted by margin — most comfortably open first — with all lanes included,
    not just open ones, so callers can reason about *how* blocked a closed lane is.
    """
    kwargs["passing_team"] = passing_team
    receivers = [
        p
        for p in state.team_state(passing_team).available()
        if p.player_id not in exclude
    ]
    assessed = [(p, assess_lane(state, origin, p.position, **kwargs)) for p in receivers]
    return sorted(assessed, key=lambda pair: pair[1].tightest_margin)


def in_cover_shadow(
    points,
    ball_position,
    defender_position,
    body_radius: float = BODY_RADIUS,
):
    """Whether point(s) sit in a defender's cover shadow.

    The cover shadow is the wedge behind the defender as seen from the ball: the region
    a direct pass cannot reach because the defender's body is in the way. Design doc §3
    needs this both as the ``cover_shadow`` defensive action and as the "edge of the
    nearest defender's cover shadow" waypoint (D-003).

    A point is shadowed when it is farther from the ball than the defender *and* within
    the angular width the defender's body subtends at that range.
    """
    p = np.asarray(points, dtype=float)
    ball = np.asarray(ball_position, dtype=float)
    defender = np.asarray(defender_position, dtype=float)

    to_defender = defender - ball
    defender_range = float(np.linalg.norm(to_defender))
    if defender_range < 1e-9:
        # Defender standing on the ball shadows nothing coherently.
        shadowed = np.zeros(p.shape[:-1], dtype=bool)
        return bool(shadowed) if p.ndim == 1 else shadowed

    axis = to_defender / defender_range
    to_point = p - ball
    along = to_point @ axis
    lateral = np.linalg.norm(to_point - along[..., None] * axis, axis=-1)

    # The shadow widens linearly with range beyond the defender.
    half_angle = np.arcsin(min(1.0, body_radius / max(defender_range, body_radius)))
    allowed = np.tan(half_angle) * np.maximum(along, 0.0)

    shadowed = (along > defender_range) & (lateral <= allowed)
    return bool(shadowed) if p.ndim == 1 else shadowed


def cover_shadow_polygon(
    ball_position,
    defender_position,
    depth: float = 30.0,
    body_radius: float = BODY_RADIUS,
) -> np.ndarray:
    """The cover-shadow wedge as a 3-point polygon, for rendering."""
    ball = np.asarray(ball_position, dtype=float)
    defender = np.asarray(defender_position, dtype=float)
    to_defender = defender - ball
    defender_range = float(np.linalg.norm(to_defender))
    if defender_range < 1e-9:
        return np.stack([ball, ball, ball])

    axis = to_defender / defender_range
    normal = np.array([-axis[1], axis[0]])
    half_angle = np.arcsin(min(1.0, body_radius / max(defender_range, body_radius)))
    spread = np.tan(half_angle) * (defender_range + depth)
    far = ball + axis * (defender_range + depth)
    return np.stack([defender, far + normal * spread, far - normal * spread])
