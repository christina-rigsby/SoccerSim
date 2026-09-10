"""Arrival-time model — the most load-bearing function in the codebase.

``time_to_point`` answers "how long until this player can be standing on that spot?".
Both the pitch-control field (:mod:`soccersim.space.pitch_control`) and the
``max_speed`` hard constraint (:mod:`soccersim.constraints.feasibility`) call it, which
is deliberate: the space layer and the constraint layer then cannot disagree about
whether a player can reach a point.

The flip side is that systematic error here biases everything downstream in the same
direction. The model is:

1. **Reaction lag** — a fixed offset from the capability profile.
2. **Turn cost** (D-017, provisional; see Q-015) — momentum not already pointing at the
   target must be arrested: ``||v - max(v.u, 0) u|| / a`` seconds, where ``u`` is the
   unit vector toward the target. A player sprinting *away* pays for killing their whole
   velocity. This is an approximation, not physics: real players turn along curved paths
   and bleed speed into the turn itself.
3. **Trapezoidal travel** — accelerate at ``max_accel`` up to ``max_speed``, then
   cruise. Short distances take the triangular branch where top speed is never reached.

Every function here is array-friendly so a whole grid of targets can be evaluated at
once.
"""

from __future__ import annotations

import numpy as np

from .domain.entities import CapabilityProfile, PlayerState


def travel_time(distance, initial_speed, max_speed: float, max_accel: float):
    """Time to cover ``distance`` under a trapezoidal velocity profile.

    ``initial_speed`` is the component of velocity already pointing at the target; it is
    clipped into ``[0, max_speed]``. Both ``distance`` and ``initial_speed`` may be
    arrays.

    Two branches:

    - **Trapezoidal** — far enough to reach ``max_speed``, then cruise the remainder.
    - **Triangular** — too short to reach ``max_speed``; accelerate the whole way,
      solving ``d = v0 t + a t^2 / 2``.
    """
    if max_speed <= 0.0 or max_accel <= 0.0:
        raise ValueError("max_speed and max_accel must be positive")

    d = np.asarray(distance, dtype=float)
    v0 = np.clip(np.asarray(initial_speed, dtype=float), 0.0, max_speed)

    # Distance and time spent accelerating from v0 up to max_speed.
    accel_distance = (max_speed**2 - v0**2) / (2.0 * max_accel)
    accel_time = (max_speed - v0) / max_accel

    trapezoidal = accel_time + np.maximum(d - accel_distance, 0.0) / max_speed
    triangular = (-v0 + np.sqrt(v0**2 + 2.0 * max_accel * d)) / max_accel

    return np.where(d >= accel_distance, trapezoidal, triangular)


def time_to_point(
    origin,
    velocity,
    capability: CapabilityProfile,
    targets,
):
    """Seconds for a body at ``origin`` with ``velocity`` to reach ``targets``.

    ``targets`` may be a single ``(2,)`` point or an ``(..., 2)`` array; the return
    shape matches (scalar in, 0-d array out).

    Includes reaction lag and turn cost as described in the module docstring.
    """
    p = np.asarray(origin, dtype=float)
    v = np.asarray(velocity, dtype=float)
    q = np.asarray(targets, dtype=float)

    delta = q - p
    distance = np.linalg.norm(delta, axis=-1)

    # Unit vector toward each target. Guarded so a zero-distance target does not divide
    # by zero; the result for those entries is overwritten below.
    safe = np.maximum(distance, 1e-12)
    direction = delta / safe[..., None]

    # Component of existing velocity already aimed at the target.
    aligned = np.sum(direction * v, axis=-1)
    usable = np.maximum(aligned, 0.0)

    # Momentum not aimed at the target has to be arrested first (D-017). When `aligned`
    # is negative `usable` is 0, so this charges for the entire velocity vector.
    residual = v - usable[..., None] * direction
    turn_time = np.linalg.norm(residual, axis=-1) / capability.max_accel

    total = (
        capability.reaction_time
        + turn_time
        + travel_time(distance, usable, capability.max_speed, capability.max_accel)
    )

    # Already standing on the target: only reaction lag applies. Without this, a player
    # moving through their own position would be charged to stop, which reads oddly for
    # a "can you be here" query.
    return np.where(distance < 1e-9, capability.reaction_time, total)


def player_time_to_point(player: PlayerState, targets):
    """:func:`time_to_point` for a player, using fatigue-degraded capability (D-006)."""
    return time_to_point(
        player.position,
        player.velocity,
        player.effective_capability(),
        targets,
    )


def team_time_to_point(players, targets):
    """Per-player arrival times, stacked.

    Returns shape ``(len(players), *target_shape)``. An empty player list yields an
    empty leading axis, which callers must handle — an empty team has no claim on any
    point rather than an infinitely fast one.
    """
    q = np.asarray(targets, dtype=float)
    target_shape = q.shape[:-1]
    if not players:
        return np.empty((0, *target_shape), dtype=float)
    return np.stack([np.asarray(player_time_to_point(p, q), dtype=float) for p in players])


def best_time_to_point(players, targets):
    """Fastest arrival time over ``players``, or ``+inf`` where there are none."""
    times = team_time_to_point(players, targets)
    if times.shape[0] == 0:
        return np.full(times.shape[1:], np.inf, dtype=float)
    return times.min(axis=0)
