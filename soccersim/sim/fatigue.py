"""Gradual fatigue and capability changes over time (substitutions, slow decline).

Every player has fresh capabilities ``state.caps_base`` and a long-term ``state.fatigue`` in
[0, 1]. The capabilities every law reads, ``state.caps``, are recomputed from the two on each
tick:

    caps = caps_base x (1 - effect[capability] x fatigue)

so a tired player is a little less precise (``configs/sim.yaml``: ``fatigue.effect``); top speed
and acceleration are reduced directly, by ``speed_effect`` and ``accel_effect`` x fatigue
(:func:`soccersim.sim.physics.max_speed`). This is separate from the short-term ``state.stamina`` (a sprint drains it,
rest refills it within a minute or so).

**Fatigue** grows with work, ``rate x (1.2 - stamina capability) x (speed / top speed)^2`` per
second (moving fast costs much more than jogging), and recovers a little while a player walks.
A scenario that starts mid-match starts with the fatigue a player would have built up by then
(``start_per_minute`` x the match minute, varying by player), unless the scenario sets it.

**Capability changes** (``state.cap_events``, from :class:`~soccersim.sim.scenarios.Scenario`
``cap_events``), each a dict:

- ``{"t": 30, "player": 9, "caps": {"pace": 0.4}, "ramp_s": 20}``: from t = 30 s, the player's
  fresh capabilities move linearly to the given values over ``ramp_s`` seconds (0: at once), e.g.
  an injury or a gradual decline;
- ``{"t": 30, "player": 9, "substitute": True, "caps": {...}}``: a substitution. A fresh player
  comes on in that slot: the given capabilities replace the old player's (those not given keep
  the slot's values), fatigue and stamina are reset, and a ``substitution`` event is recorded.
"""

from __future__ import annotations

import numpy as np

from ..schema.vocab import CAPABILITIES
from .events import emit
from .state import CAP_INDEX, MatchState, team_of


def effect_vector(cfg: dict) -> np.ndarray:
    eff = ((cfg.get("fatigue") or {}).get("effect")) or {}
    return np.array([float(eff.get(c, 0.0)) for c in CAPABILITIES])


def refresh_caps(state: MatchState, cfg: dict) -> None:
    """Recompute the effective capabilities from the fresh ones and the fatigue."""
    if state.caps_base is None:
        state.caps_base = state.caps.copy()
    if not (cfg.get("fatigue") or {}).get("enabled", False):
        state.caps = state.caps_base.copy()
        return
    state.caps = np.clip(state.caps_base * (1.0 - effect_vector(cfg)[None, :] * state.fatigue[:, None]), 0.0, 1.0)


def initial_fatigue(rng: np.random.Generator, minute: float, cfg: dict, level: float | None = None) -> np.ndarray:
    """Fatigue at the start of a scenario: built up by ``minute``, or around ``level`` if given."""
    fc = cfg.get("fatigue") or {}
    if not fc.get("enabled", False):
        return np.zeros(22)
    mean = float(level) if level is not None else float(fc.get("start_per_minute", 0.0)) * float(minute)
    if mean <= 0:
        return np.zeros(22)  # (draws nothing, so the scenario's random stream is unchanged)
    return np.clip(mean * rng.uniform(0.7, 1.3, size=22), 0.0, 1.0)


def _apply_events(state: MatchState) -> None:
    for ev in state.cap_events:
        if state.t + 1e-9 < float(ev["t"]) or ev.get("_done"):
            continue
        p = int(ev["player"])
        caps = ev.get("caps") or {}
        if ev.get("substitute"):
            for k, v in caps.items():
                state.caps_base[p, CAP_INDEX[k]] = float(v)
            state.fatigue[p] = 0.0
            state.stamina[p] = 1.0
            emit(state, "substitution", team_of(p), p, state.pos[p])
            ev["_done"] = True
            continue
        if "_from" not in ev:
            ev["_from"] = {k: float(state.caps_base[p, CAP_INDEX[k]]) for k in caps}
        ramp = float(ev.get("ramp_s", 0.0))
        w = 1.0 if ramp <= 0 else min(1.0, (state.t - float(ev["t"])) / ramp)
        for k, v in caps.items():
            state.caps_base[p, CAP_INDEX[k]] = ev["_from"][k] + w * (float(v) - ev["_from"][k])
        if w >= 1.0:
            ev["_done"] = True


def update(state: MatchState, frac: np.ndarray, cfg: dict, dt: float) -> None:
    """One tick: apply due capability changes, accumulate fatigue, refresh the capabilities."""
    if state.caps_base is None:
        state.caps_base = state.caps.copy()
    if state.cap_events:
        _apply_events(state)
    fc = cfg.get("fatigue") or {}
    if fc.get("enabled", False):
        endurance = state.caps_base[:, CAP_INDEX["stamina"]]
        gain = float(fc["rate"]) * (1.2 - endurance) * np.clip(frac, 0.0, 1.0) ** 2
        rest = np.where(frac < float(fc.get("rest_frac", 0.3)), float(fc.get("recover_per_s", 0.0)), 0.0)
        state.fatigue = np.clip(state.fatigue + (gain - rest) * dt, 0.0, 1.0)
    refresh_caps(state, cfg)
