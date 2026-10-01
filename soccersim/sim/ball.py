"""Ball commands, flight, control and possession (spec §7.2 Ball / Pass / Control).

Everything here works in absolute coordinates. Controllers speak in team frames; the
env converts before calling in.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import shots as shots_mod
from .duels import control_prob
from .events import emit
from .passmodel import assess_pass, noisy_target, passer_pressure
from .physics import max_speed
from .restarts import award_restart, kickoff
from .state import CAP_INDEX, DIRECTION, Flight, MatchState, team_of, team_players


@dataclass
class BallCommand:
    kind: str                     # pass | shoot | clear
    target: np.ndarray            # absolute
    style: str = "ground"
    receiver: int = -1
    placement: str = "auto"


def to_frame(team: int, p: np.ndarray) -> np.ndarray:
    return DIRECTION[team] * np.asarray(p, dtype=float)


def offside_players(state: MatchState, team: int) -> frozenset[int]:
    """Attackers in an offside position at this instant (evaluated at pass release)."""
    d = DIRECTION[team]
    opp = 1 - team
    opp_x = np.sort(d * state.pos[list(team_players(opp)), 0])
    second_last = opp_x[-2] if len(opp_x) >= 2 else 52.5
    ball_x = d * state.ball.pos[0]
    line = max(second_last, ball_x)
    out = []
    for i in team_players(team):
        if i == state.ball.owner:
            continue
        x = d * state.pos[i, 0]
        if x > 0.0 and x > line + 1e-6:
            out.append(i)
    return frozenset(out)


def nearest_opponent_distance(state: MatchState, player: int) -> float:
    opp = list(team_players(1 - team_of(player)))
    return float(np.min(np.linalg.norm(state.pos[opp] - state.pos[player], axis=1)))


# -- control ---------------------------------------------------------------------------


def gain_control(state: MatchState, player: int, cfg: dict, cause: str = "control") -> None:
    """``player`` takes the ball. Emits pass / possession events."""
    ball = state.ball
    team = team_of(player)
    flight = ball.flight
    if flight is not None and flight.kind == "pass" and team == flight.team and player in flight.offside \
            and cfg.get("offside", {}).get("enabled", True):
        emit(state, "offside", team, player, state.pos[player])
        award_restart(state, "free_kick", 1 - team, state.pos[player].copy(), cfg)
        return
    prev = state.last_control_team
    ball.owner = player
    ball.flight = None
    ball.height = "ground"
    ball.vel = state.vel[player].copy()
    ball.pos = state.pos[player].copy()
    ball.owner_since = state.t
    ball.last_touch_team = team
    ball.last_touch_player = player
    if flight is not None and flight.kind in ("pass", "clear"):
        if team == flight.team:
            emit(state, "pass_completed", team, player, data_from=flight.passer)
        else:
            emit(state, "pass_intercepted", flight.team, player)
    if prev is not None and prev != team:
        emit(state, "possession_won", team, player, cause=cause)
        emit(state, "possession_lost", 1 - team, player, cause=cause)
        if cause == "tackle":
            emit(state, "tackle_won", team, player)
    state.possession = team
    state.last_control_team = team


def release(state: MatchState, cmd: BallCommand, cfg: dict, rng: np.random.Generator) -> None:
    """Execute an on-ball command from the current owner."""
    ball = state.ball
    passer = ball.owner
    if passer < 0:
        return
    team = team_of(passer)
    opp = list(team_players(1 - team))
    origin = state.pos[passer].copy()

    if cmd.kind == "shoot":
        _release_shot(state, passer, cmd, cfg, rng)
        return

    style = cmd.style if cmd.kind != "clear" else "clear"
    pressure = passer_pressure(origin, state.pos[opp])
    skill = state.caps[passer, CAP_INDEX["crossing" if style in ("whipped", "driven_low") else "passing"]]
    target = noisy_target(rng, origin, np.asarray(cmd.target, float), style, float(skill), pressure, cfg,
                          cfg.get("noise_scale", 1.0))
    vmax = max_speed(state, cfg)
    recv = cmd.receiver
    assess = assess_pass(
        origin, target, style, state.pos[opp], state.vel[opp], vmax[opp], cfg,
        receiver_pos=state.pos[recv] if recv >= 0 else None,
        receiver_vmax=float(vmax[recv]) if recv >= 0 else 8.0,
        receiver_aerial=float(state.caps[recv, CAP_INDEX["aerial"]]) if recv >= 0 else 0.5,
        opp_aerial=state.caps[opp, CAP_INDEX["aerial"]],
    )
    plan = assess.plan
    flight = Flight(
        kind="clear" if cmd.kind == "clear" else "pass", team=team, passer=passer, receiver=recv, style=style,
        target=target, release_t=state.t, air=plan.air, duration=plan.duration,
        offside=offside_players(state, team),
    )
    if not plan.air and len(opp):
        # Sample the interception from the same per-opponent probabilities lane_open uses,
        # in order of where along the path each opponent would meet the ball.
        order = np.argsort(assess.best_idx)
        for j in order:
            if rng.random() < assess.p_intercept[j]:
                k = assess.best_idx[j]
                flight.intercept_player = opp[j]
                flight.intercept_point = plan.points[k].copy()
                flight.intercept_t = state.t + float(plan.times[k])
                break
    ball.owner = -1
    ball.flight = flight
    ball.last_touch_team = team
    ball.last_touch_player = passer
    state.touch_cooldown[passer] = state.t + 0.4
    delta = target - origin
    dist = float(np.hypot(*delta))
    unit = delta / dist if dist > 1e-6 else np.array([DIRECTION[team], 0.0])
    if plan.air:
        ball.height = "air"
        ball.vel = unit * dist / max(plan.duration, 1e-3)
    else:
        ball.height = "ground"
        ball.vel = unit * plan.v0
    ball.pos = origin + unit * 0.3


def _release_shot(state: MatchState, shooter: int, cmd: BallCommand, cfg: dict, rng: np.random.Generator) -> None:
    ball = state.ball
    team = team_of(shooter)
    d = DIRECTION[team]
    opp = list(team_players(1 - team))
    pos_f = d * state.pos[shooter]
    pressure = passer_pressure(state.pos[shooter], state.pos[opp])
    header = state.t - ball.last_aerial_t < 0.6
    xg_v = shots_mod.xg(pos_f, pressure, header, cfg)
    gk = state.gk(1 - team)
    gk_f = d * state.pos[gk] if gk >= 0 else None
    p_goal = shots_mod.goal_probability(
        xg_v, state.caps[shooter, CAP_INDEX["finishing"]], shots_mod.gk_factor(pos_f, gk_f, cfg), cfg
    )
    outcome = shots_mod.sample_outcome(rng, p_goal, cfg)
    tgt_f = shots_mod.shot_target(rng, outcome, pos_f, gk_f, cmd.placement)
    target = d * tgt_f
    dist = float(np.hypot(*(target - state.pos[shooter])))
    speed = cfg["shot"]["shot_speed"]
    flight = Flight(kind="shot", team=team, passer=shooter, receiver=-1, style="shot", target=target,
                    release_t=state.t, air=False, duration=max(dist / speed, 0.1), shot_outcome=outcome,
                    xg=float(xg_v), header=header)
    emit(state, "shot_taken", team, shooter, state.pos[shooter], xg=round(float(xg_v), 4), outcome=outcome,
         frame_pos=[round(float(pos_f[0]), 2), round(float(pos_f[1]), 2)])
    ball.owner = -1
    ball.flight = flight
    ball.height = "ground"
    ball.vel = (target - state.pos[shooter]) / flight.duration
    ball.last_touch_team = team
    ball.last_touch_player = shooter
    state.touch_cooldown[shooter] = state.t + 0.5


# -- per-tick ball update ----------------------------------------------------------------


def step_ball(state: MatchState, cfg: dict, rng: np.random.Generator, dt: float) -> None:
    ball = state.ball
    if state.restart is not None:
        ball.vel[:] = 0.0
        ball.pos = state.restart.pos.copy()
        return
    if ball.owner >= 0:
        o = ball.owner
        v = state.vel[o]
        sp = float(np.hypot(*v))
        head = v / sp if sp > 0.3 else np.array([DIRECTION[team_of(o)], 0.0])
        ball.pos = state.pos[o] + head * cfg["ball"]["dribble_offset"]
        ball.vel = v.copy()
        _check_out(state, cfg)
        return

    fl = ball.flight
    t_rel = state.t - fl.release_t if fl else 0.0

    if fl is not None and fl.kind == "shot":
        ball.pos = ball.pos + ball.vel * dt
        if t_rel >= fl.duration:
            _resolve_shot(state, fl, cfg)
        return

    if fl is not None and fl.air and ball.height == "air":
        ball.pos = ball.pos + ball.vel * dt
        if t_rel >= fl.duration:
            ball.pos = fl.target.copy()
            _resolve_landing(state, fl, cfg, rng)
        return

    # Ground ball (pass in flight, arrived pass, or loose).
    speed = float(np.hypot(*ball.vel))
    if speed > 0:
        new_speed = max(0.0, speed - cfg["ball"]["friction"] * dt)
        ball.pos = ball.pos + ball.vel * dt
        ball.vel = ball.vel * (new_speed / speed)
    if _check_out(state, cfg):
        return

    arrived = fl is None or t_rel >= fl.duration
    if fl is not None and not arrived:
        # Planned interception.
        if fl.intercept_player >= 0 and state.t >= fl.intercept_t:
            j = fl.intercept_player
            if np.hypot(*(state.pos[j] - ball.pos)) < 2.5:
                gain_control(state, j, cfg, cause="interception")
                return
            fl.intercept_player = -1
        # Intended receiver meeting the ball early.
        r = fl.receiver
        if r >= 0 and t_rel > 0.2 and np.hypot(*(state.pos[r] - ball.pos)) < cfg["ball"]["control_radius"] + 0.4:
            _attempt_control(state, r, cfg, rng)
        return
    _loose_ball_contest(state, cfg, rng)


def _attempt_control(state: MatchState, player: int, cfg: dict, rng: np.random.Generator) -> bool:
    ball = state.ball
    if state.touch_cooldown[player] > state.t:
        return False
    speed = float(np.hypot(*ball.vel))
    p = control_prob(state, player, speed, nearest_opponent_distance(state, player), cfg)
    if rng.random() < p:
        gain_control(state, player, cfg)
        return True
    # Failed touch: the ball squirms away.
    ang = rng.uniform(0, 2 * np.pi)
    # A miscontrolled soft ball stays close; a hard one bounces further.
    bounce = min(cfg["control"]["deflect_speed"], 1.0 + 0.35 * speed)
    ball.vel = np.array([np.cos(ang), np.sin(ang)]) * bounce
    ball.flight = None
    ball.last_touch_team = team_of(player)
    ball.last_touch_player = player
    state.touch_cooldown[player] = state.t + 0.5
    if state.possession is not None:
        state.possession = None
    return False


def _loose_ball_contest(state: MatchState, cfg: dict, rng: np.random.Generator) -> None:
    ball = state.ball
    d = np.linalg.norm(state.pos - ball.pos, axis=1)
    radius = np.full(len(d), cfg["ball"]["control_radius"])
    for team in (0, 1):
        gk = state.gk(team)
        if gk >= 0 and DIRECTION[team] * ball.pos[0] < -36 and abs(ball.pos[1]) < 20.16:
            radius[gk] = 2.0
    cand = np.where((d < radius) & (state.touch_cooldown <= state.t))[0]
    for i in cand[np.argsort(d[cand])]:
        if _attempt_control(state, int(i), cfg, rng):
            return
    if ball.flight is not None and float(np.hypot(*ball.vel)) < 0.3:
        # A pass that stopped with nobody on it is a loose ball.
        ball.flight = None
        state.possession = None


def _resolve_landing(state: MatchState, fl: Flight, cfg: dict, rng: np.random.Generator) -> None:
    ball = state.ball
    ball.height = "ground"
    ball.last_aerial_t = state.t
    if _check_out(state, cfg):
        return
    r = cfg["ball"]["air_contest_radius"]
    d = np.linalg.norm(state.pos - ball.pos, axis=1)
    near = np.where(d < r)[0]
    unit = ball.vel / max(float(np.hypot(*ball.vel)), 1e-6)
    if len(near) == 0:
        ball.vel = unit * 5.0
        fl.duration = 0.0  # arrived; ball rolls on as a loose ball attributed to the pass
        return
    aer = state.caps[near, CAP_INDEX["aerial"]] + 0.5 * (1.0 - d[near] / r)
    teams = {team_of(int(i)) for i in near}
    if len(teams) == 2:
        w = np.maximum(aer, 0.05)
        winner = int(rng.choice(near, p=w / w.sum()))
    else:
        winner = int(near[np.argmin(d[near])])
    ft = state.caps[winner, CAP_INDEX["first_touch"]]
    p = cfg["pass"]["aerial_base_success"] * (0.75 + 0.25 * ft) * (0.8 if len(teams) == 2 else 1.0)
    if rng.random() < p:
        gain_control(state, winner, cfg, cause="aerial")
    else:
        ang = rng.uniform(0, 2 * np.pi)
        ball.vel = np.array([np.cos(ang), np.sin(ang)]) * 4.0
        ball.flight = None
        ball.last_touch_team = team_of(winner)
        ball.last_touch_player = winner
        state.possession = None
        state.touch_cooldown[winner] = state.t + 0.4


def _resolve_shot(state: MatchState, fl: Flight, cfg: dict) -> None:
    team = fl.team
    other = 1 - team
    if fl.shot_outcome == "goal":
        state.score[team] += 1
        emit(state, "goal", team, fl.passer)
        emit(state, "goal_conceded", other, fl.passer)
        kickoff(state, other, cfg)
    elif fl.shot_outcome == "caught":
        gk = state.gk(other)
        state.ball.pos = state.pos[gk].copy()
        gain_control(state, gk, cfg, cause="save")
    elif fl.shot_outcome == "parried_corner":
        emit(state, "ball_out", None)
        emit(state, "ball_out_them_last", team)
        corner_y = np.sign(fl.target[1] or 1.0) * 34.0
        award_restart(state, "corner", team, np.array([DIRECTION[team] * 52.5, corner_y]), cfg)
    else:
        emit(state, "ball_out", None)
        emit(state, "ball_out_them_last", other)
        gk_x = DIRECTION[other] * -47.0
        award_restart(state, "goal_kick", other, np.array([gk_x, 0.0]), cfg)


def _check_out(state: MatchState, cfg: dict) -> bool:
    ball = state.ball
    hl = cfg["pitch"]["length"] / 2
    hw = cfg["pitch"]["width"] / 2
    x, y = ball.pos
    if abs(y) <= hw and abs(x) <= hl:
        return False
    last = ball.last_touch_team if ball.last_touch_team >= 0 else 0
    emit(state, "ball_out", None)
    emit(state, "ball_out_them_last", 1 - last)
    if abs(y) > hw:
        award_restart(state, "throw_in", 1 - last, np.array([np.clip(x, -hl + 1, hl - 1), np.sign(y) * hw]), cfg)
        return True
    # Over a goal line. The defending team is the one whose own goal is on that end.
    defending = 1 if x > 0 else 0
    attacking = 1 - defending
    if last == defending:
        award_restart(state, "corner", attacking, np.array([np.sign(x) * hl, np.sign(y or 1.0) * hw]), cfg)
    else:
        award_restart(state, "goal_kick", defending, np.array([np.sign(x) * (hl - 5.5), 0.0]), cfg)
    return True
