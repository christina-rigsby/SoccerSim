"""Restarts: throw-ins, goal kicks, corners, free kicks and kickoffs (spec §7.2 Restarts).

A restart freezes the ball for a short setup time while players reorganise, then hands
it to the taker. Set-piece plays (``build_out_short_goal_kick``) override the default
restart behaviour by triggering on the ``goal_kick_ours`` event.
"""

from __future__ import annotations

import numpy as np

from .events import emit
from .state import DIRECTION, MatchState, Restart, team_players


def award_restart(state: MatchState, rtype: str, team: int, pos: np.ndarray, cfg: dict) -> None:
    ball = state.ball
    ball.owner = -1
    ball.flight = None
    ball.height = "ground"
    ball.vel = np.zeros(2)
    ball.pos = np.asarray(pos, float).copy()
    prev = state.last_control_team
    if prev is not None and prev != team:
        emit(state, "possession_won", team, cause=rtype)
        emit(state, "possession_lost", 1 - team, cause=rtype)
    state.possession = team
    state.last_control_team = team
    if rtype == "goal_kick":
        taker = state.gk(team)
    else:
        idx = [i for i in team_players(team) if state.kinds[i] != "GK"]
        taker = idx[int(np.argmin(np.linalg.norm(state.pos[idx] - pos, axis=1)))]
    setup = cfg["restarts"]["kickoff_setup_s" if rtype == "kickoff" else "setup_s"]
    state.restart = Restart(rtype, team, ball.pos.copy(), state.t + setup, taker)


def kickoff(state: MatchState, team: int, cfg: dict) -> None:
    """Reset to kickoff shape with ``team`` kicking off."""
    for tm in (0, 1):
        d = DIRECTION[tm]
        for i in team_players(tm):
            base = state.base_out[i].copy()
            base[0] = min(base[0] * 0.9, -1.5)
            state.pos[i] = d * base
            state.vel[i] = 0.0
    award_restart(state, "kickoff", team, np.zeros(2), cfg)
    taker = state.restart.taker
    state.pos[taker] = np.array([-DIRECTION[team] * 0.5, 0.0])


def execute_restart(state: MatchState, cfg: dict) -> str:
    """Hand the ball to the taker once setup time has elapsed. Returns the restart type."""
    rs = state.restart
    taker = rs.taker
    state.pos[taker] = rs.pos.copy()
    state.vel[taker] = 0.0
    # Opponents retreat 9 m from the ball at a restart.
    for i in team_players(1 - rs.team):
        off = state.pos[i] - rs.pos
        dist = float(np.hypot(*off))
        if dist < 9.0:
            unit = off / dist if dist > 1e-6 else np.array([-DIRECTION[rs.team], 0.0])
            state.pos[i] = rs.pos + unit * 9.15
    state.restart = None
    ball = state.ball
    ball.owner = taker
    ball.owner_since = state.t
    ball.last_touch_team = rs.team
    ball.last_touch_player = taker
    state.possession = rs.team
    state.last_control_team = rs.team
    if rs.type == "goal_kick":
        emit(state, "goal_kick_ours", rs.team, taker)
        emit(state, "goal_kick_theirs", 1 - rs.team, taker)
    elif rs.type == "corner":
        emit(state, "corner_ours", rs.team, taker)
    elif rs.type == "throw_in":
        emit(state, "throw_in_ours", rs.team, taker)
    return rs.type
