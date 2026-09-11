"""Single-frame measurements — what is observably true right now.

Everything here is a *measurement*, not an inference: a pure function of one
:class:`~soccersim.domain.state.GameState` with no history and no uncertainty. That
separation is deliberate. Block height is a fact you can read off the pitch; marking
scheme is a hypothesis you accumulate evidence for. Mixing the two would mean wrapping
facts in confidence machinery that has nothing to say about them.

Reuses what already exists rather than recomputing it:
:meth:`TeamState.shape`, :meth:`TeamState.centroid` and
:meth:`TeamState.defensive_line_x` already cover §2's formation-shape requirement, and
:func:`soccersim.kinematics.player_time_to_point` supplies every arrival time.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np

from ..domain.entities import PlayerState, PositionalRole, Team
from ..domain.pitch import Pitch
from ..domain.state import GameState, TeamState
from ..kinematics import player_time_to_point

#: An opponent who can reach the carrier within this is applying pressure.
PRESSURE_HORIZON = 2.0  # seconds

#: Only opponents inside this radius are considered part of a pressing action at all,
#: so a distant sprint back does not register as pressure.
PRESSURE_RADIUS = 18.0  # metres


class BlockType(Enum):
    """How deep a team is defending, from §3's mid-block / low-block strategies."""

    HIGH = "high"
    MID = "mid"
    LOW = "low"


#: Defensive-line height, as a fraction of the distance from own goal to halfway, that
#: separates the three block types. Conventional rather than fitted (Q-025).
LOW_BLOCK_CEILING = 0.34
HIGH_BLOCK_FLOOR = 0.72


def outfield(team_state: TeamState) -> list[PlayerState]:
    """Available players excluding the goalkeeper.

    Most shape questions want this: the keeper is always the deepest player, so
    including them drags every depth measurement toward their own goal.
    """
    return [
        player
        for player in team_state.available()
        if not player.positional_role.is_goalkeeper
    ]


def _progress(team_state: TeamState, players: list[PlayerState]) -> np.ndarray:
    """Each player's ``x`` signed so larger is further upfield for this team."""
    if not players:
        return np.empty(0, dtype=float)
    return np.array(
        [team_state.attacking_direction * player.position[0] for player in players]
    )


@dataclass(frozen=True)
class DefensiveLine:
    """The back line's position and geometry."""

    height: float  #: mean progress of the line, in metres from the halfway line
    tilt: float  #: progress difference between the highest and deepest line member
    width: float  #: lateral spread of the line
    gaps: tuple[float, ...]  #: lateral gaps between adjacent line members
    player_ids: tuple[int, ...]  #: line members, widest-left first

    @property
    def largest_gap(self) -> float:
        return max(self.gaps) if self.gaps else 0.0

    @property
    def largest_gap_between(self) -> tuple[int, int] | None:
        """The pair of players straddling the widest gap.

        This is what §3's "midpoint of the gap between CB and fullback" waypoint needs,
        found by measurement rather than by assuming which slots are adjacent.
        """
        if not self.gaps:
            return None
        index = int(np.argmax(self.gaps))
        return self.player_ids[index], self.player_ids[index + 1]


def defensive_line(team_state: TeamState, count: int = 4) -> DefensiveLine | None:
    """Geometry of the ``count`` deepest outfield players.

    Excludes the goalkeeper, unlike :meth:`TeamState.defensive_line_x`, which documents
    that it includes them. Both are useful; this is the one for line-breaking questions.
    """
    players = outfield(team_state)
    if len(players) < 2:
        return None
    progress = _progress(team_state, players)
    order = np.argsort(progress)[: min(count, len(players))]
    line = [players[i] for i in order]
    line.sort(key=lambda player: float(player.position[1]))

    ys = np.array([player.position[1] for player in line])
    line_progress = _progress(team_state, line)
    return DefensiveLine(
        height=float(line_progress.mean()),
        tilt=float(line_progress.max() - line_progress.min()),
        width=float(ys.max() - ys.min()),
        gaps=tuple(float(g) for g in np.diff(ys)),
        player_ids=tuple(player.player_id for player in line),
    )


def block_height(team_state: TeamState) -> float:
    """Mean progress of the outfield players, in metres relative to the halfway line.

    Positive means the team's centre of gravity is in the opponent's half.
    """
    progress = _progress(team_state, outfield(team_state))
    return float(progress.mean()) if len(progress) else float("nan")


def block_type(team_state: TeamState, pitch: Pitch, count: int = 4) -> BlockType | None:
    """Classify the defensive block as high, mid or low.

    A *measurement* with conventional thresholds, not an inference: it describes where
    the line is right now, and says nothing about whether the team intends to keep it
    there. "Are they playing a low block" in the strategic sense needs history, and lives
    with the estimators.

    Describes line height irrespective of possession, so a team camped in the opponent's
    half reads ``HIGH`` whether or not they currently have the ball.
    """
    line = defensive_line(team_state, count)
    if line is None:
        return None
    # 0 at their own goal line, 1 at the halfway line — and above 1 when the line has
    # pushed into the opponent's half, which still classifies as HIGH.
    fraction = (line.height + pitch.half_length) / pitch.half_length
    if fraction <= LOW_BLOCK_CEILING:
        return BlockType.LOW
    if fraction >= HIGH_BLOCK_FLOOR:
        return BlockType.HIGH
    return BlockType.MID


@dataclass(frozen=True)
class Pressure:
    """How hard the player on the ball is being pressed."""

    carrier_id: int | None
    #: Opponents who could reach the carrier within :data:`PRESSURE_HORIZON`.
    pressing_ids: tuple[int, ...]
    #: Soonest any opponent could arrive, in seconds. ``inf`` when nobody is near.
    nearest_arrival: float
    #: Aggregate closing speed of the *committed* opponents only, m/s.
    closing_speed: float
    #: Arrival time of each committed opponent, parallel to ``pressing_ids``.
    arrivals: tuple[float, ...] = ()

    @property
    def count(self) -> int:
        return len(self.pressing_ids)

    @property
    def is_pressed(self) -> bool:
        return self.nearest_arrival <= PRESSURE_HORIZON

    @property
    def intensity(self) -> float:
        """A single scalar, roughly ``0`` (free) to ``3+`` (swarmed).

        Only opponents who could actually reach the carrier within
        :data:`PRESSURE_HORIZON` contribute; each adds its own proximity plus its own
        closing rate. Deliberately unbounded above, since being closed down by three
        players really is worse than by two and clipping would hide that.

        The gating is the important part. An earlier version summed closing speed over
        everyone within :data:`PRESSURE_RADIUS` whether or not they could get there,
        which meant defenders merely *drifting back toward their own shape* past the
        ball registered as a press — and that phantom press then got credited to
        whichever pass preceded it, corrupting the trigger rates downstream.
        """
        if not self.pressing_ids:
            return 0.0
        proximity = sum(
            max(0.0, PRESSURE_HORIZON - arrival) / PRESSURE_HORIZON
            for arrival in self.arrivals
        )
        return float(proximity + max(0.0, self.closing_speed) / 10.0)


def pressure_on(state: GameState, player_id: int) -> Pressure:
    """Pressure applied to one player by the opposing team.

    §2 lists "pressure on ball carrier" under team state; this is that, generalised to
    any player so it also answers "would this receiver be under pressure".
    """
    target = state.player(player_id)
    opponents = state.opponents_of(target.team).available()

    pressing: list[int] = []
    arrivals: list[float] = []
    nearest = float("inf")
    closing = 0.0
    for opponent in opponents:
        offset = target.position - opponent.position
        distance = float(np.linalg.norm(offset))
        if distance > PRESSURE_RADIUS:
            continue
        arrival = float(player_time_to_point(opponent, target.position))
        nearest = min(nearest, arrival)
        if arrival > PRESSURE_HORIZON:
            continue
        pressing.append(opponent.player_id)
        arrivals.append(arrival)
        if distance > 1e-9:
            # Component of this committed opponent's velocity aimed at the target.
            closing += max(0.0, float(opponent.velocity @ (offset / distance)))

    return Pressure(
        carrier_id=player_id,
        pressing_ids=tuple(pressing),
        nearest_arrival=nearest,
        closing_speed=closing,
        arrivals=tuple(arrivals),
    )


def pressure_on_ball(state: GameState) -> Pressure | None:
    """Pressure on the current ball carrier, or ``None`` when nobody has the ball."""
    if state.ball.carrier_id is None:
        return None
    return pressure_on(state, state.ball.carrier_id)


def zone_occupancy(team_state: TeamState, pitch: Pitch) -> dict[tuple[str, str], int]:
    """Outfield players per (third, channel) cell.

    The coarse positional picture the opponent model's zone estimates are compared
    against, and the basis for the situation key that §5's ``predictability_penalty``
    buckets play usage by.
    """
    counts: dict[tuple[str, str], int] = {}
    for player in outfield(team_state):
        key = (
            pitch.third(player.position, team_state.attacking_direction),
            pitch.channel(player.position),
        )
        counts[key] = counts.get(key, 0) + 1
    return counts


@dataclass(frozen=True)
class TeamShape:
    """Everything measurable about one team's shape in one frame."""

    team: Team
    centroid: np.ndarray
    width: float
    depth: float
    compactness: float
    block_height: float
    block: BlockType | None
    line: DefensiveLine | None
    players_available: int

    def describe(self) -> str:
        block = self.block.value if self.block else "n/a"
        line = f"{self.line.height:+.1f}m" if self.line else "n/a"
        return (
            f"{self.team.value}: {self.players_available} avail  "
            f"w {self.width:.0f}m  d {self.depth:.0f}m  "
            f"compact {self.compactness:.1f}m  block {block} "
            f"(height {self.block_height:+.1f}m, line {line})"
        )


def team_shape(team_state: TeamState, pitch: Pitch) -> TeamShape:
    """Compose the existing shape helpers into one frame-level reading."""
    shape = team_state.shape()
    return TeamShape(
        team=team_state.team,
        centroid=team_state.centroid(),
        width=shape["width"],
        depth=shape["depth"],
        compactness=shape["compactness"],
        block_height=block_height(team_state),
        block=block_type(team_state, pitch),
        line=defensive_line(team_state),
        players_available=len(team_state.available()),
    )


def situation_key(state: GameState, team: Team) -> tuple[str, str, str]:
    """A coarse bucket for "similar opponent situation".

    §5's ``predictability_penalty`` is "proportional to recent-usage count of a given
    play against *similar opponent situations*", which needs a definition of similar.
    This is the deliberately coarse one: where the ball is, how deep the opponent sits,
    and the match phase. Coarse on purpose — too fine a key and every situation is
    unique, so no play ever looks repetitive (Q-026).
    """
    opponents = state.opponents_of(team)
    block = block_type(opponents, state.pitch)
    return (
        state.pitch.third(state.ball.position, state.attacking_direction(team)),
        block.value if block else "unknown",
        state.phase.value,
    )
