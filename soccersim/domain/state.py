"""Team and whole-game state containers."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .entities import BallState, GamePhase, PlayerState, Team
from .pitch import Pitch


@dataclass
class TeamState:
    """One team's players and which way they are attacking."""

    team: Team
    players: list[PlayerState] = field(default_factory=list)
    attacking_direction: int = 1  # +1 attacks +x, -1 attacks -x (D-012)

    def available(self) -> list[PlayerState]:
        return [p for p in self.players if p.available]

    def by_id(self, player_id: int) -> PlayerState:
        for p in self.players:
            if p.player_id == player_id:
                return p
        raise KeyError(f"no player {player_id} in team {self.team.value}")

    def positions(self) -> np.ndarray:
        """``(n, 2)`` array of available players' positions."""
        avail = self.available()
        if not avail:
            return np.empty((0, 2), dtype=float)
        return np.stack([p.position for p in avail])

    def velocities(self) -> np.ndarray:
        """``(n, 2)`` array of available players' velocities."""
        avail = self.available()
        if not avail:
            return np.empty((0, 2), dtype=float)
        return np.stack([p.velocity for p in avail])

    # -- formation shape (design doc §2) --------------------------------------

    def centroid(self) -> np.ndarray:
        pos = self.positions()
        if len(pos) == 0:
            return np.array([np.nan, np.nan])
        return pos.mean(axis=0)

    def shape(self) -> dict[str, float]:
        """Width, depth and compactness of the current formation.

        Compactness is the mean distance of players from their own centroid — lower is
        more compact. Reported alongside width/depth because a team can be wide and
        shallow or narrow and stretched with the same mean spread.
        """
        pos = self.positions()
        if len(pos) < 2:
            return {"width": 0.0, "depth": 0.0, "compactness": 0.0}
        centre = pos.mean(axis=0)
        return {
            "width": float(pos[:, 1].max() - pos[:, 1].min()),
            "depth": float(pos[:, 0].max() - pos[:, 0].min()),
            "compactness": float(np.linalg.norm(pos - centre, axis=1).mean()),
        }

    def defensive_line_x(self, count: int = 4) -> float:
        """Mean ``x`` of the ``count`` deepest available players.

        "Deepest" is relative to ``attacking_direction``, so this is comparable across
        both halves. Note that the goalkeeper is normally the deepest player and so is
        included in the default ``count=4``; pass ``count=5`` to get the keeper plus a
        back four, or filter by role first for the outfield line alone.
        """
        pos = self.positions()
        if len(pos) == 0:
            return float("nan")
        progress = np.sort(self.attacking_direction * pos[:, 0])
        return float(progress[: min(count, len(progress))].mean() * self.attacking_direction)


@dataclass
class GameState:
    """Everything the space layer needs to evaluate a moment.

    The dashboard (module 1, M2) will grow the opponent model and historical "book"
    around this; M0 carries only what the geometry layer reads.
    """

    pitch: Pitch
    home: TeamState
    away: TeamState
    ball: BallState
    score: tuple[int, int] = (0, 0)  # (home, away)
    clock_seconds: float = 0.0
    phase: GamePhase = GamePhase.OPEN_PLAY
    possession: Team | None = None

    def team_state(self, team: Team) -> TeamState:
        return self.home if team is Team.HOME else self.away

    def opponents_of(self, team: Team) -> TeamState:
        return self.team_state(team.other)

    def attacking_direction(self, team: Team) -> int:
        return self.team_state(team).attacking_direction

    def all_players(self) -> list[PlayerState]:
        return list(self.home.players) + list(self.away.players)

    def player(self, player_id: int) -> PlayerState:
        for p in self.all_players():
            if p.player_id == player_id:
                return p
        raise KeyError(f"no player with id {player_id}")

    def team_of(self, player_id: int) -> Team:
        return self.player(player_id).team
