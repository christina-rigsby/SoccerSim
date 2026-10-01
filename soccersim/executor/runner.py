"""Per-team directive assembly: active play + shape controller + automatic behaviours.

Priority, highest first:

1. Restart setup — the taker walks to the ball; everyone else takes shape.
2. Ball-in-flight reflexes — the intended receiver meets the ball, the sampled
   interceptor attacks the interception point.
3. Loose ball — each team's quickest player chases it.
4. The active play's directives for bound players.
5. Defaults: the keeper covers the goal, the nearest free defender engages the carrier,
   a ball carrier with nothing to do shields, and everyone else holds shape (spec §7.4).
"""

from __future__ import annotations

import numpy as np

from ..controllers import Directive
from ..controllers.shape import shape_targets
from ..dashboard.team_state import TeamView
from .instance import PlayInstance


def team_directives(view: TeamView, active: PlayInstance | None) -> dict[int, Directive]:
    state = view.state
    team = view.team
    shape_cfg = view.ctx.formations["shape"]
    out: dict[int, Directive] = {}

    rs = state.restart
    in_poss = view.possession == "us"
    shape = shape_targets(state, team, in_poss, view.ball, shape_cfg)
    for k, p in enumerate(view.us):
        dist = float(np.hypot(*(shape[k] - view.pos[p])))
        out[int(p)] = Directive(shape[k], 0.55 if dist < 8 else 0.8, label="shape")

    if rs is not None:
        if rs.team == team and rs.taker >= 0:
            out[rs.taker] = Directive(view.d * rs.pos, 1.0, label="restart")
        return out

    play_dirs: dict[int, Directive] = {}
    if active is not None and not active.ended:
        play_dirs = active.tick(view)
        out.update(play_dirs)

    bound = active.bound_players if active is not None and not active.ended else set()

    # Defaults for unbound players.
    gk = state.gk(team)
    if gk >= 0 and gk not in bound and view.possession != "us":
        to_ball = view.ball - np.array([-52.5, 0.0])
        dist = float(np.hypot(*to_ball))
        pt = np.array([-52.5, 0.0]) + to_ball / max(dist, 1e-6) * min(5.0, max(dist * 0.25, 1.0))
        out[gk] = Directive(pt, 0.8, label="set_position")
    if view.holder >= 0 and view.holder not in play_dirs:
        out[view.holder] = Directive(view.pos[view.holder].copy(), 0.0, protect=True, label="shield")
    if view.opp_holder >= 0:
        carrier = view.pos[view.opp_holder]
        free = [int(p) for p in view.outfield(view.us) if p not in bound]
        if free:
            t_all = np.linalg.norm(view.pos[view.us] - carrier, axis=1) / view.vmax[view.us]
            t_free = np.linalg.norm(view.pos[free] - carrier, axis=1) / view.vmax[free]
            engaged_by_play = any(
                out[int(p)].mode in ("press", "tackle", "jockey") for p in view.us if int(p) in bound
            )
            if not engaged_by_play and t_free.min() <= t_all.min() + 1e-9:
                presser = free[int(np.argmin(t_free))]
                out[presser] = Directive(carrier.copy(), 0.85, mode="press", label="press")

    _reflexes(view, out)
    return out


def _reflexes(view: TeamView, out: dict[int, Directive]) -> None:
    state = view.state
    ball = state.ball
    fl = ball.flight
    team = view.team
    if ball.owner >= 0:
        return
    if fl is not None and state.t - fl.release_t < fl.duration and fl.kind != "shot":
        if fl.team == team and fl.receiver >= 0:
            out[fl.receiver] = Directive(view.d * fl.target, 1.0, label="receive")
        if fl.team != team and fl.intercept_player >= 0 and fl.intercept_point is not None:
            out[fl.intercept_player] = Directive(view.d * fl.intercept_point, 1.0, label="intercept")
        if fl.air and fl.team != team:
            # Defend the landing spot with the nearest defender.
            land = view.d * fl.target
            of = view.outfield(view.us)
            p = int(of[np.argmin(np.linalg.norm(view.pos[of] - land, axis=1))])
            out[p] = Directive(land, 1.0, label="contest")
        return
    if fl is not None and fl.kind == "shot":
        return
    # Loose ball: the quickest player of this team chases a short projection of it.
    aim = view.ball + view.ball_vel * 0.4
    pool = [int(p) for p in view.us if state.kinds[p] != "GK" or view.ball[0] < -36.0]
    t = np.linalg.norm(view.pos[pool] - aim, axis=1) / view.vmax[pool]
    p = pool[int(np.argmin(t))]
    out[p] = Directive(np.clip(aim, [-52.5, -34], [52.5, 34]), 1.0, label="chase")
