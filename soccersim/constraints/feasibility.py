"""Hard constraints — the binary pass/fail pre-filter.

Design doc §5 splits constraints by one test: *is violating this ever acceptable if the
alternative is worse?* If yes it is soft (a penalty, feeding the weight sum); if no it is
hard (a prune). Hard checks run before path weights or the assignment solve, because the
assignment solve is the expensive step (D-005).

This module implements the subset the M0 foundation can honestly support — the ones that
need only kinematics and geometry:

===========================  =====================================
``max_speed``                :func:`check_reachable`
``pitch_bounds``             :func:`check_in_bounds`
``offside``                  :func:`check_offside`
``collision``                :func:`check_separation`
===========================  =====================================

The remaining hard constraints from §5 — ``single_ball``, ``player_count``,
``possession_state``, ``eligibility``, ``min_role_coverage``, ``time_remaining``,
``set_piece_context`` — need the ``Play`` and ``RoleRequirement`` types, so they arrive
with M1. :data:`Violation` is shaped so they slot in unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np

from ..domain.entities import PlayerState, Waypoint
from ..domain.pitch import Pitch
from ..domain.state import GameState, TeamState
from ..kinematics import player_time_to_point

#: Minimum separation between two teammates' simultaneous positions, in metres.
DEFAULT_MIN_SEPARATION = 1.5


@dataclass(frozen=True)
class Violation:
    """A failed hard constraint. Truthy, so ``if violation:`` reads naturally."""

    constraint: str
    detail: str

    def __str__(self) -> str:
        return f"{self.constraint}: {self.detail}"


@dataclass(frozen=True)
class Reachability:
    """Result of a kinematic reachability check.

    ``slack`` is the spare time in seconds — positive means the player arrives early.
    It is returned rather than discarded because the *margin* is what a soft constraint
    would want later: a waypoint met with 0.05 s to spare is feasible but fragile.
    """

    feasible: bool
    arrival_time: float
    deadline: float

    @property
    def slack(self) -> float:
        return self.deadline - self.arrival_time


def reachability(player: PlayerState, waypoint: Waypoint) -> Reachability:
    """Can ``player`` be at ``waypoint.target`` by ``waypoint.deadline``?

    Uses fatigue-degraded capability (D-006) via the same arrival-time model as the
    pitch-control layer, so the two cannot disagree.
    """
    arrival = float(player_time_to_point(player, waypoint.target))
    return Reachability(
        feasible=arrival <= waypoint.deadline + 1e-9,
        arrival_time=arrival,
        deadline=float(waypoint.deadline),
    )


def check_reachable(player: PlayerState, waypoint: Waypoint) -> Violation | None:
    """``max_speed`` (§5): waypoint reachable in time given speed and acceleration."""
    result = reachability(player, waypoint)
    if result.feasible:
        return None
    return Violation(
        "max_speed",
        f"player {player.player_id} needs {result.arrival_time:.2f}s to reach "
        f"{np.round(waypoint.target, 1).tolist()} but the deadline is "
        f"{result.deadline:.2f}s (short by {-result.slack:.2f}s)",
    )


def check_in_bounds(waypoint: Waypoint, pitch: Pitch) -> Violation | None:
    """``pitch_bounds`` (§5): every waypoint inside the field of play."""
    if pitch.contains(waypoint.target):
        return None
    return Violation(
        "pitch_bounds",
        f"waypoint {np.round(waypoint.target, 1).tolist()} for player "
        f"{waypoint.player_id} is outside the field of play",
    )


def is_offside(
    receiver_position,
    ball_position,
    defender_positions,
    attacking_direction: int,
) -> bool:
    """Whether a player receiving at ``receiver_position`` would be offside.

    All three exemptions apply, and level counts as onside throughout:

    - in your own half (or on the halfway line) is never offside;
    - level with or behind the ball is never offside;
    - level with the second-last defender is onside — only *beyond* is offside.

    ``defender_positions`` should be all defending players including the goalkeeper,
    since the second-last defender is usually the last outfielder but need not be.
    """
    s = float(np.sign(attacking_direction)) or 1.0
    receiver = np.asarray(receiver_position, dtype=float)
    ball = np.asarray(ball_position, dtype=float)
    defenders = np.asarray(defender_positions, dtype=float).reshape(-1, 2)

    progress = s * receiver[0]
    if progress <= 0.0:
        return False  # own half or halfway line
    if progress <= s * ball[0]:
        return False  # level with or behind the ball

    if len(defenders) < 2:
        # Fewer than two defenders upfield of nobody — no offside line exists.
        return True

    defender_progress = np.sort(s * defenders[:, 0])[::-1]
    second_last = float(defender_progress[1])
    return progress > second_last


def check_offside(
    waypoint: Waypoint,
    state: GameState,
    attacking_team: TeamState,
) -> Violation | None:
    """``offside`` (§5): a receiving waypoint beyond the second-last defender is invalid.

    Evaluated against the defence's *current* positions. Design doc §5 specifies the
    moment of the pass, which needs the event-trigger representation (Q-009) to pin
    down; until then this is a snapshot approximation and will read as offside for runs
    timed to beat a stepping-up line.
    """
    defenders = state.opponents_of(attacking_team.team).available()
    if is_offside(
        waypoint.target,
        state.ball.position,
        [d.position for d in defenders],
        attacking_team.attacking_direction,
    ):
        return Violation(
            "offside",
            f"player {waypoint.player_id} receiving at "
            f"{np.round(waypoint.target, 1).tolist()} is beyond the second-last defender",
        )
    return None


def check_separation(
    waypoints: Iterable[Waypoint],
    min_separation: float = DEFAULT_MIN_SEPARATION,
) -> Violation | None:
    """``collision`` (§5): no two teammates required in the same space at the same time.

    Two waypoints conflict when they are closer than ``min_separation`` *and* their
    deadlines are close enough that the players would be there together. The time test
    matters: a play where two players occupy the same pocket three seconds apart is a
    rotation, not a collision.
    """
    points = list(waypoints)
    for i, first in enumerate(points):
        for second in points[i + 1 :]:
            if first.player_id == second.player_id:
                continue
            gap = float(np.linalg.norm(first.target - second.target))
            if gap >= min_separation:
                continue
            # Time to cross the remaining gap at a walking pace — below this the two
            # arrivals overlap in space and time.
            simultaneity_window = max(0.5, (min_separation - gap) / 2.0)
            if abs(first.deadline - second.deadline) <= simultaneity_window:
                return Violation(
                    "collision",
                    f"players {first.player_id} and {second.player_id} are both required "
                    f"within {gap:.2f}m at t≈{first.deadline:.2f}s "
                    f"(minimum separation {min_separation:.2f}m)",
                )
    return None


def check_waypoints(
    state: GameState,
    attacking_team: TeamState,
    waypoints: Iterable[Waypoint],
    *,
    receiving_waypoints: Iterable[int] = (),
    min_separation: float = DEFAULT_MIN_SEPARATION,
) -> list[Violation]:
    """Run every M0 hard check over a set of waypoints and collect the failures.

    ``receiving_waypoints`` names the player ids whose waypoint is a ball-receiving one,
    since offside applies only to those. Returns every violation rather than
    short-circuiting — when authoring a play by hand, seeing all the problems at once is
    more useful than being told about them one at a time.
    """
    points = list(waypoints)
    receiving = set(receiving_waypoints)
    violations: list[Violation] = []

    for waypoint in points:
        if (found := check_in_bounds(waypoint, state.pitch)) is not None:
            violations.append(found)
        try:
            player = attacking_team.by_id(waypoint.player_id)
        except KeyError:
            violations.append(
                Violation(
                    "eligibility",
                    f"player {waypoint.player_id} is not an available member of "
                    f"team {attacking_team.team.value}",
                )
            )
            continue
        if not player.available:
            violations.append(
                Violation("eligibility", f"player {player.player_id} is unavailable")
            )
            continue
        if (found := check_reachable(player, waypoint)) is not None:
            violations.append(found)
        if waypoint.player_id in receiving:
            if (found := check_offside(waypoint, state, attacking_team)) is not None:
                violations.append(found)

    if (found := check_separation(points, min_separation)) is not None:
        violations.append(found)

    return violations
