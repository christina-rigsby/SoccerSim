"""The pass model — shared by execution and by the ``lane_open`` predicate (spec §7.2).

For each opponent: time-to-intercept at sampled points along the ball path vs. the
ball's arrival time there, using a Spearman-style reaction time. Interception
probability is a logistic function of the time margin. Aerial balls are uncontested in
flight and contested on landing. ``lane_open`` calls :func:`pass_success` with no noise;
execution samples noise first and then samples the interception from the same
probabilities, so the two can never disagree about what the model says.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

AIR_STYLES = ("lofted", "whipped", "clear")


def _sigmoid(z):
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))


def is_air(style: str) -> bool:
    return style in AIR_STYLES


@dataclass
class PassPlan:
    air: bool
    v0: float                # ground launch speed (0 for air)
    duration: float          # seconds until the ball reaches the target
    s: np.ndarray            # (S,) distances along the path
    points: np.ndarray       # (S, 2)
    times: np.ndarray        # (S,) ball arrival time at each point (inf if it stops short)


def plan_pass(origin: np.ndarray, target: np.ndarray, style: str, cfg: dict) -> PassPlan:
    pc = cfg["pass"]
    delta = target - origin
    dist = float(np.hypot(*delta))
    n = pc["path_samples"]
    s = np.linspace(0.0, max(dist, 1e-3), n)
    unit = delta / dist if dist > 1e-6 else np.array([1.0, 0.0])
    points = origin[None, :] + s[:, None] * unit[None, :]
    if is_air(style):
        speed = pc["flight_speed"].get(style, 18.0)
        duration = 0.35 + dist / speed
        times = s / max(dist, 1e-3) * duration
        return PassPlan(True, 0.0, duration, s, points, times)
    f = cfg["ball"]["friction"]
    v_end = pc["arrival_speed"].get(style, 7.0)
    v0 = min(float(np.sqrt(v_end**2 + 2.0 * f * dist)), cfg["ball"]["max_ground_speed"])
    disc = v0**2 - 2.0 * f * s
    times = np.where(disc >= 0, (v0 - np.sqrt(np.maximum(disc, 0.0))) / f, np.inf)
    duration = float(times[-1]) if np.isfinite(times[-1]) else float(v0 / f)
    return PassPlan(False, v0, duration, s, points, times)


def arrival_times(points: np.ndarray, pos: np.ndarray, vel: np.ndarray, vmax: np.ndarray, reaction: float):
    """(n_players, S) Spearman-style time for each player to reach each point."""
    start = pos + vel * reaction
    d = np.linalg.norm(points[None, :, :] - start[:, None, :], axis=2)
    return reaction + d / vmax[:, None]


@dataclass
class PassAssessment:
    p_success: float
    p_intercept: np.ndarray     # (n_opp,)
    best_idx: np.ndarray        # (n_opp,) index into plan.points of each opp's best interception point
    p_receiver: float
    plan: PassPlan


def assess_pass(
    origin: np.ndarray,
    target: np.ndarray,
    style: str,
    opp_pos: np.ndarray,
    opp_vel: np.ndarray,
    opp_vmax: np.ndarray,
    cfg: dict,
    receiver_pos: np.ndarray | None = None,
    receiver_vmax: float = 8.0,
    receiver_aerial: float = 0.5,
    opp_aerial: np.ndarray | None = None,
) -> PassAssessment:
    pc = cfg["pass"]
    plan = plan_pass(origin, target, style, cfg)
    react = pc["reaction_time"]
    k = pc["intercept_sharpness"]
    bias = pc["intercept_bias"]
    n_opp = len(opp_pos)

    t_recv = 0.0
    if receiver_pos is not None:
        t_recv = float(np.hypot(*(target - receiver_pos))) / max(receiver_vmax, 1e-3)

    if n_opp == 0:
        p_int = np.zeros(0)
        best = np.zeros(0, dtype=int)
    elif plan.air:
        # Uncontested in flight; contested on landing.
        t_opp = arrival_times(plan.points[-1:], opp_pos, opp_vel, opp_vmax, react)[:, 0]
        land = plan.duration
        # An opponent contests the landing if they arrive before the ball does, or
        # before the receiver does.
        margin = np.maximum(land, t_recv) + 0.3 - t_opp
        contest = _sigmoid(k * margin)
        aer = opp_aerial if opp_aerial is not None else np.full(n_opp, 0.5)
        win_share = aer / (aer + receiver_aerial + 1e-6)
        p_int = contest * win_share
        best = np.full(n_opp, len(plan.s) - 1)
    else:
        t_opp = arrival_times(plan.points, opp_pos, opp_vel, opp_vmax, react)  # (n_opp, S)
        margin = plan.times[None, :] - t_opp - bias
        # Ignore the first metre: the passer's own feet.
        margin[:, plan.s < 1.0] = -np.inf
        best = np.argmax(margin, axis=1)
        p_int = _sigmoid(k * margin[np.arange(n_opp), best])

    p_recv = 1.0
    if receiver_pos is not None:
        kr = pc["receiver_sharpness"]
        p_recv = float(_sigmoid(kr * (plan.duration + 0.6 - t_recv)))
        if plan.air:
            p_recv *= pc["aerial_base_success"]
    p_success = float(np.prod(1.0 - p_int) * p_recv) if n_opp else p_recv
    return PassAssessment(p_success, p_int, best, p_recv, plan)


def passer_pressure(passer_pos: np.ndarray, opp_pos: np.ndarray) -> float:
    if len(opp_pos) == 0:
        return 0.0
    d = float(np.min(np.linalg.norm(opp_pos - passer_pos, axis=1)))
    return float(np.exp(-d / 2.0))


def noisy_target(
    rng: np.random.Generator,
    origin: np.ndarray,
    target: np.ndarray,
    style: str,
    passing: float,
    pressure: float,
    cfg: dict,
    noise_scale: float = 1.0,
) -> np.ndarray:
    """Apply execution noise: angular error and length error, scaled by skill and pressure."""
    nz = cfg["pass"]["noise"]
    mult = nz["style_multiplier"].get(style, 1.0) * noise_scale * (1.0 + nz["pressure_gain"] * pressure)
    ang_sigma = np.deg2rad(nz["angle_base_deg"]) * (1.0 - passing) * mult
    len_sigma = nz["speed_base"] * (1.0 - passing) * mult
    delta = target - origin
    ang = rng.normal(0.0, ang_sigma)
    c, s = np.cos(ang), np.sin(ang)
    rot = np.array([c * delta[0] - s * delta[1], s * delta[0] + c * delta[1]])
    return origin + rot * max(0.3, 1.0 + rng.normal(0.0, len_sigma))
