"""Shape controller — default behaviour for players not bound to a play role (spec §7.4).

Each slot's target is its formation base position (in- or out-of-possession shape),
shifted toward the ball by team-level compactness parameters. In possession, players
ahead of the ball hold just onside; out of possession nobody stays far ahead of the
ball.
"""

from __future__ import annotations

import numpy as np

from ..sim.state import DIRECTION, MatchState, team_players


def offside_line_x(state: MatchState, team: int) -> float:
    """x (team frame) of the second-last opponent — the offside line for ``team``."""
    d = DIRECTION[team]
    xs = np.sort(d * state.pos[list(team_players(1 - team)), 0])
    return float(xs[-2]) if len(xs) >= 2 else 52.5


def shape_targets(state: MatchState, team: int, in_possession: bool, ball_frame: np.ndarray,
                  shape_cfg: dict) -> np.ndarray:
    """(11, 2) team-frame shape targets for ``team``'s players in slot order."""
    idx = list(team_players(team))
    base = (state.base_in if in_possession else state.base_out)[idx].copy()
    width = shape_cfg["width_in"] if in_possession else shape_cfg["width_out"]
    tgt = base.copy()
    tgt[:, 1] = base[:, 1] * width + shape_cfg["shift_y"] * ball_frame[1]
    shift_x = shape_cfg["shift_x_in" if in_possession else "shift_x_out"]
    tgt[:, 0] = base[:, 0] + shift_x * ball_frame[0]
    gk = np.array([state.kinds[i] == "GK" for i in idx])
    # Keeper: stays near goal, shades toward the ball.
    tgt[gk, 0] = -52.5 + np.clip(4.0 + 0.08 * (ball_frame[0] + 52.5), 3.0, 16.0)
    tgt[gk, 1] = np.clip(ball_frame[1] * 0.12, -3.0, 3.0)
    if in_possession:
        line = max(offside_line_x(state, team), ball_frame[0])
        cap = line - shape_cfg["onside_margin"]
        # Nobody can be offside in their own half, so the cap never goes below halfway.
        tgt[~gk, 0] = np.minimum(tgt[~gk, 0], max(cap, 0.0))
    else:
        tgt[~gk, 0] = np.minimum(tgt[~gk, 0], ball_frame[0] + shape_cfg["max_depth_ahead_of_ball_out"])
    tgt[:, 0] = np.clip(tgt[:, 0], -51.5, 51.5)
    tgt[:, 1] = np.clip(tgt[:, 1], -33.0, 33.0)
    return tgt
