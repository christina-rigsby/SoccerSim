"""Player movement and stamina (spec §7.2 Movement).

Each tick every player has a steering target and a desired speed fraction. Players
accelerate toward the desired velocity under their acceleration limit, brake so they
can stop on the target, and are capped at a stamina-scaled top speed.
"""

from __future__ import annotations

import numpy as np

from .state import CAP_INDEX, MatchState


def max_speed(state: MatchState, cfg: dict) -> np.ndarray:
    mv = cfg["movement"]
    base = mv["base_speed"] + mv["pace_speed"] * state.caps[:, CAP_INDEX["pace"]]
    floor = mv["stamina_speed_floor"]
    return base * (floor + (1.0 - floor) * state.stamina)


def max_accel(state: MatchState, cfg: dict) -> np.ndarray:
    mv = cfg["movement"]
    return mv["base_accel"] + mv["accel_gain"] * state.caps[:, CAP_INDEX["acceleration"]]


def step_players(
    state: MatchState,
    targets: np.ndarray,
    speed_frac: np.ndarray,
    cfg: dict,
    dt: float,
) -> None:
    """Advance every player one tick toward ``targets`` (absolute coords)."""
    vmax = max_speed(state, cfg)
    amax = max_accel(state, cfg)

    # The ball carrier is slowed; a protecting carrier more so (applied via speed_frac
    # by the caller for protect, here for the dribble cap).
    owner = state.ball.owner
    cap = np.ones(len(vmax))
    if owner >= 0:
        cap[owner] = cfg["movement"]["dribble_speed_factor"]
    stunned = state.stun_until > state.t
    cap[stunned] = np.minimum(cap[stunned], 0.3)

    delta = targets - state.pos
    dist = np.linalg.norm(delta, axis=1)
    direction = np.divide(delta, dist[:, None], out=np.zeros_like(delta), where=dist[:, None] > 1e-6)
    # Brake so the player can stop on the target: v <= sqrt(2 a d).
    want_speed = np.minimum(np.clip(speed_frac, 0.0, 1.0) * vmax * cap, np.sqrt(2.0 * amax * dist * 0.9))
    desired = direction * want_speed[:, None]

    # Soft separation so players do not stack on one point.
    sep_r = cfg["movement"]["separation_radius"]
    diff = state.pos[:, None, :] - state.pos[None, :, :]
    d2 = np.einsum("ijk,ijk->ij", diff, diff)
    np.fill_diagonal(d2, np.inf)
    close = d2 < sep_r**2
    if close.any():
        push = np.where(close[:, :, None], diff / np.sqrt(np.maximum(d2, 1e-6))[:, :, None], 0.0).sum(axis=1)
        desired = desired + push * 1.5

    dv = desired - state.vel
    dv_norm = np.linalg.norm(dv, axis=1)
    limit = amax * dt
    scale = np.where(dv_norm > limit, limit / np.maximum(dv_norm, 1e-9), 1.0)
    state.vel = state.vel + dv * scale[:, None]
    speed = np.linalg.norm(state.vel, axis=1)
    over = speed > vmax * cap
    if over.any():
        state.vel[over] *= ((vmax * cap)[over] / speed[over])[:, None]
        speed = np.linalg.norm(state.vel, axis=1)
    state.pos = state.pos + state.vel * dt

    hl = cfg["pitch"]["length"] / 2 + 3.0
    hw = cfg["pitch"]["width"] / 2 + 3.0
    np.clip(state.pos[:, 0], -hl, hl, out=state.pos[:, 0])
    np.clip(state.pos[:, 1], -hw, hw, out=state.pos[:, 1])

    _stamina(state, speed / np.maximum(vmax, 1e-6), cfg, dt)


def _stamina(state: MatchState, frac: np.ndarray, cfg: dict, dt: float) -> None:
    st = cfg["stamina"]
    sprinting = frac > st["sprint_threshold"]
    endurance = state.caps[:, CAP_INDEX["stamina"]]
    drain = st["drain_per_s"] * (1.2 - endurance) * frac * dt
    recover = st["recover_per_s"] * dt
    state.stamina = np.clip(np.where(sprinting, state.stamina - drain, state.stamina + recover), 0.0, 1.0)
