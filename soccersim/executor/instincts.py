"""Player instincts: what players do when no play tells them what to do.

Plays direct a few players for a few seconds. Before instincts, everyone else only held the
team shape, and a ball carrier outside any play stood still shielding the ball. Real players
improvise, so two instincts fill those gaps (configs/ranking.yaml: ``instincts``):

**Ball carrier** (outside any play): every ``decide_every_s`` it compares

- *holding* the ball where it is,
- *passing* to each teammate whose pass would arrive with probability at least ``min_pass_p``,
- *carrying* the ball ``carry_dist_m`` in one of a fan of mostly forward directions,

and does the best one. Every option is valued the same way: the value of the ball being at a
spot is ``V(p) = c(p) * xT(p) - (1 - c(p)) * xT_them(p)``, where ``c`` is our pitch control
there (would we get there first) and ``xT`` the chance that possession at that spot ends in a
goal (``xT_them`` the same for the opponent). A pass is worth
``P(arrives) * V(target) + (1 - P(arrives)) * (-xT_them(target))``. Holding risks a tackle:
it loses the ball with probability ``hold_risk * exp(-(d - 1) / press_scale_m)``, where ``d`` is
the distance to the nearest opponent. Passing and carrying must beat holding by a margin, so
the carrier does not dither between near-equal options.

**Off-ball players** (in possession, outside the play, not the keeper, not the ``rest_defence``
deepest outfield players): every ``every_s`` each looks at spots around its place in the team
shape (within ``radius_m``), onside, at least ``spacing_m`` from the spots already chosen by
teammates, and moves to the one with the highest ``w_value * c(p) * (xT(p) + open_base)``
minus ``w_shape`` per metre from its place in the shape: space we control, and more so where
it is dangerous. Players nearest the ball choose first.

Decisions are kept in ``state.memo`` between re-evaluations, so a copied game state carries them.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np

from ..config import load_config
from ..controllers.base import Directive, FrameBallCommand, clip_pitch
from ..dashboard.team_state import TeamView


@lru_cache(maxsize=1)
def instincts_config() -> dict:
    return dict(load_config("ranking").get("instincts") or {})


def _value_us(view: TeamView, pts: np.ndarray) -> np.ndarray:
    """Value of the ball being at each point: our threat if we control it, their threat if not."""
    pts = np.atleast_2d(pts)
    c = view.pc(pts)
    return c * view.xt(pts) - (1.0 - c) * view.xt(-pts)


def enabled_for(view: TeamView, part: str) -> bool:
    """Whether this team uses an instinct (``carrier`` / ``off_ball``). A team opts out of some or
    all of them through ``state.memo[("no_instincts", team)]``: True (all) or a set of parts,
    set from a policy spec's ``instincts`` (false, or the list of parts it keeps)."""
    off = view.state.memo.get(("no_instincts", view.team))
    if off is True or (off and part in off):
        return False
    return bool((instincts_config().get(part) or {}).get("enabled", False))


def _memo(view: TeamView, key: str) -> dict:
    return view.state.memo.setdefault((key, view.team), {})


# -- ball carrier --------------------------------------------------------------------------


def carrier_instinct(view: TeamView, cfg: dict | None = None) -> Directive | None:
    """Directive for our ball carrier when no play directs it (None = keep the default)."""
    if cfg is None and not enabled_for(view, "carrier"):
        return None
    cfg = cfg if cfg is not None else (instincts_config().get("carrier") or {})
    if not cfg.get("enabled", False):
        return None
    h = view.holder
    if h < 0 or view.state.kinds[h] == "GK" or view.state.restart is not None:
        return None
    mem = _memo(view, "carrier")
    if mem.get("holder") != h or view.t - mem.get("t", -1e9) >= float(cfg.get("decide_every_s", 0.4)) - 1e-9:
        mem.clear()
        mem.update(holder=h, t=view.t, choice=_choose(view, h, cfg))
    kind, pt, recv = mem["choice"]
    counts = view.state.memo.setdefault(("instinct_counts", view.team), {})
    counts[kind] = counts.get(kind, 0) + (kind != "carry" or mem.get("counted") != h)
    mem["counted"] = h
    if kind == "pass":
        mem["t"] = -1e9  # a pass is a one-off: decide afresh next time we have the ball
        return Directive(view.pos[h].copy(), 0.0, FrameBallCommand("pass", pt, "ground", recv), label="instinct_pass")
    if kind == "carry":
        if np.hypot(*(pt - view.pos[h])) < 1.5:
            mem["t"] = -1e9
            return None
        return Directive(pt, 0.9, label="instinct_carry")
    return None


def _choose(view: TeamView, h: int, cfg: dict) -> tuple[str, np.ndarray | None, int]:
    here = view.pos[h]
    # Holding still under pressure risks a tackle: the closer the nearest opponent, the likelier
    # we lose the ball before the next decision (pitch control at our own feet misses this).
    d = view.nearest_opponent_dist(h)
    p_lose = float(cfg.get("hold_risk", 0.5)) * float(np.exp(-max(d - 1.0, 0.0) / float(cfg.get("press_scale_m", 2.0))))
    v_hold = (1.0 - p_lose) * float(_value_us(view, here)[0]) - p_lose * float(view.xt(-np.atleast_2d(here))[0])
    best = ("hold", None, -1, v_hold)
    # Carry: a fan of mostly forward directions.
    dist = float(cfg.get("carry_dist_m", 6.0))
    angles = np.radians(cfg.get("carry_angles_deg", [-75, -45, -20, 0, 20, 45, 75]))
    pts = np.array([clip_pitch(here + dist * np.array([np.cos(a), np.sin(a)]), 1.0) for a in angles])
    vals = _value_us(view, pts)
    k = int(np.argmax(vals))
    if vals[k] > v_hold + float(cfg.get("carry_margin", 0.002)) and vals[k] > best[3]:
        best = ("carry", pts[k], -1, float(vals[k]))
    # Pass: to each teammate, once we have settled on the ball.
    if view.t - view.state.ball.owner_since >= float(cfg.get("settle_s", 0.3)):
        min_p = float(cfg.get("min_pass_p", 0.55))
        margin = float(cfg.get("pass_margin", 0.004))
        for i in view.us:
            i = int(i)
            if i == h or view.state.kinds[i] == "GK" or not view.onside(i):
                continue
            target = view.pos[i]
            p = view.pass_p(h, target, "ground", i)
            if p < min_p:
                continue
            v = p * float(_value_us(view, target)[0]) - (1.0 - p) * float(view.xt(-np.atleast_2d(target))[0])
            if v > v_hold + margin and v > best[3]:
                best = ("pass", target.copy(), i, v)
    return best[0], best[1], best[2]


# -- off-ball movement -----------------------------------------------------------------------


def off_ball_targets(view: TeamView, shape: dict[int, np.ndarray], bound: set[int],
                     cfg: dict | None = None) -> dict[int, np.ndarray]:
    """Space-seeking targets for our unbound outfield players while we have the ball.

    ``shape`` maps each of our players to its place in the team shape (team frame).
    """
    if cfg is None and not enabled_for(view, "off_ball"):
        return {}
    cfg = cfg if cfg is not None else (instincts_config().get("off_ball") or {})
    if not cfg.get("enabled", False) or view.possession != "us" or view.state.restart is not None:
        return {}
    mem = _memo(view, "off_ball")
    fresh = view.t - mem.get("t", -1e9) < float(cfg.get("every_s", 0.5)) - 1e-9
    if fresh and mem.get("bound") == sorted(bound) and mem.get("holder") == view.holder:
        return mem["targets"]
    h = view.holder
    outfield = [int(p) for p in view.outfield(view.us) if int(p) != h and int(p) not in bound]
    # Rest defence: the deepest outfield players (by their place in the shape) stay put.
    n_rest = int(cfg.get("rest_defence", 2))
    all_out = sorted((int(p) for p in view.outfield(view.us)), key=lambda p: shape[p][0])
    rest = set(all_out[:n_rest])
    movers = sorted((p for p in outfield if p not in rest),
                    key=lambda p: float(np.hypot(*(shape[p] - view.ball))))
    rings = [0.0, *cfg.get("rings_m", [4.0, 9.0])]
    radius = float(cfg.get("radius_m", 9.0))
    spacing = float(cfg.get("spacing_m", 7.0))
    w_value, w_shape = float(cfg.get("w_value", 1.0)), float(cfg.get("w_shape", 0.0005))
    open_base = float(cfg.get("open_base", 0.01))
    angles = np.radians(np.arange(0, 360, 45))
    offsets = np.array([[0.0, 0.0]] + [[r * np.cos(a), r * np.sin(a)] for r in rings[1:] for a in angles])
    offsets = offsets[np.hypot(offsets[:, 0], offsets[:, 1]) <= radius + 1e-9]
    offside = view.offside_x - 0.5
    taken = [view.pos[h]] if h >= 0 else []
    taken += [view.pos[p] for p in bound if p != h]
    targets: dict[int, np.ndarray] = {}
    for p in movers:
        cand = np.array([clip_pitch(shape[p] + o, 1.5) for o in offsets])
        cand[:, 0] = np.minimum(cand[:, 0], max(offside, shape[p][0]))
        c = view.pc(cand)
        score = w_value * c * (view.xt(cand) + open_base) - w_shape * np.hypot(*(cand - shape[p]).T)
        if taken:
            d = np.min(np.linalg.norm(cand[:, None, :] - np.array(taken)[None, :, :], axis=2), axis=1)
            score = np.where(d < spacing, score - 1.0, score)
        pt = cand[int(np.argmax(score))]
        targets[p] = pt
        taken.append(pt)
    mem.update(t=view.t, bound=sorted(bound), holder=h, targets=targets)
    return targets
