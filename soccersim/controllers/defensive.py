"""Defensive and keeper controllers: press, cover, mark, block, jockey, tackle, recover,
group line shifts, and goalkeeper positioning."""

from __future__ import annotations

import numpy as np

from .base import ControllerCtx, Directive, clip_pitch, controller, hold, move_target, speed_of

OWN_GOAL = np.array([-52.5, 0.0])


def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.hypot(*v))
    return v / n if n > 1e-6 else np.array([-1.0, 0.0])


def _opp(ctx: ControllerCtx, params: dict, key: str = "target") -> int:
    t = params.get(key)
    if isinstance(t, dict) and "opponent" in t:
        return ctx.ev.selector(t["opponent"])
    if isinstance(t, str):
        return ctx.ev.selector(t)
    if isinstance(t, dict):
        _, who = ctx.ev.target(t)
        return who
    return ctx.ev.selector("ball_carrier")


@controller("press")
def press(ctx: ControllerCtx, player: int, params: dict, mem: dict) -> Directive:
    v = ctx.view
    o = _opp(ctx, params)
    if o < 0:
        return hold(ctx, player, "press")
    tgt = v.pos[o].copy()
    curve = params.get("curve", "none")
    if curve in ("force_outside", "force_inside"):
        # Approach from the inside (to force play outside) by standing on that side.
        inward = -np.sign(tgt[1] or 1.0)
        shift = 1.2 if curve == "force_outside" else -1.2
        tgt = tgt + np.array([-0.8, inward * shift])
    intensity = float(params.get("intensity", 1.0))
    return Directive(clip_pitch(tgt), 0.55 + 0.45 * intensity, mode="press", label="press")


@controller("tackle")
def tackle(ctx: ControllerCtx, player: int, params: dict, mem: dict) -> Directive:
    o = _opp(ctx, params)
    if o < 0:
        return hold(ctx, player, "tackle")
    return Directive(ctx.view.pos[o].copy(), 1.0, mode="tackle", label="tackle")


@controller("jockey")
def jockey(ctx: ControllerCtx, player: int, params: dict, mem: dict) -> Directive:
    v = ctx.view
    o = _opp(ctx, params)
    if o < 0:
        return hold(ctx, player, "jockey")
    pt = v.pos[o] + _unit(OWN_GOAL - v.pos[o]) * 2.5
    return Directive(clip_pitch(pt), 0.9, mode="jockey", label="jockey")


@controller("mark")
def mark(ctx: ControllerCtx, player: int, params: dict, mem: dict) -> Directive:
    v = ctx.view
    o = _opp(ctx, params)
    if o < 0:
        return hold(ctx, player, "mark")
    ctx.ev.marked.add(o)
    tight = float(params.get("tightness", 2.0))
    toward = OWN_GOAL if params.get("goal_side", True) else v.ball
    pt = v.pos[o] + _unit(toward - v.pos[o]) * tight
    return Directive(clip_pitch(pt), 0.9, mode="jockey" if v.owner == o else "default", label="mark")


@controller("block_lane")
def block_lane(ctx: ControllerCtx, player: int, params: dict, mem: dict) -> Directive:
    v = ctx.view
    a = ctx.ev.selector(params["from"])
    b = ctx.ev.selector(params["to"])
    if a < 0 or b < 0 or a == b:
        return hold(ctx, player, "block_lane")
    pa, pb = v.pos[a], v.pos[b]
    seg = pb - pa
    L2 = float(np.dot(seg, seg))
    s = float(np.clip(np.dot(v.pos[player] - pa, seg) / L2, 0.3, 0.7)) if L2 > 1e-6 else 0.5
    return Directive(clip_pitch(pa + s * seg), 0.9, mode="none", label="block_lane")


@controller("cover")
def cover(ctx: ControllerCtx, player: int, params: dict, mem: dict) -> Directive:
    v = ctx.view
    who = ctx.ev.player(params["behind"])
    if who < 0:
        return hold(ctx, player, "cover")
    depth = float(params.get("depth", 8.0))
    pt = v.pos[who] + _unit(OWN_GOAL - v.pos[who]) * depth
    return Directive(clip_pitch(pt), 0.8, label="cover")


@controller("block_shot")
def block_shot(ctx: ControllerCtx, player: int, params: dict, mem: dict) -> Directive:
    v = ctx.view
    pt = v.ball + _unit(OWN_GOAL - v.ball) * 3.0
    return Directive(clip_pitch(pt), 1.0, mode="default", label="block_shot")


@controller("recover")
def recover(ctx: ControllerCtx, player: int, params: dict, mem: dict) -> Directive:
    v = ctx.view
    if "to" in params:
        pt, _ = move_target(ctx, player, params["to"], mem)
    else:
        pt = np.array([max(v.ball[0] - 12.0, -45.0), v.ball[1] * 0.5])
    if pt is None:
        return hold(ctx, player, "recover")
    return Directive(clip_pitch(pt), speed_of(params, "max"), label="recover")


def _line_slot(ctx: ControllerCtx, player: int, height: float, width: float, ball_shift: float) -> np.ndarray:
    """This member's slot in a group line: x from line height, y spread across width."""
    v = ctx.view
    members = ctx.group or [player]
    order = sorted(members, key=lambda i: -v.state.base_out[i, 1])
    n = len(order)
    k = order.index(player) if player in order else 0
    centre = float(v.ball[1]) * ball_shift
    y = centre if n == 1 else centre + width * (0.5 - k / (n - 1))
    x = height - 52.5
    return clip_pitch(np.array([x, y]), 1.0)


@controller("compact_shift")
def compact_shift(ctx: ControllerCtx, player: int, params: dict, mem: dict) -> Directive:
    pt = _line_slot(ctx, player, float(params["line_height"]), float(params["width"]),
                    float(params.get("ball_shift", 0.5)))
    return Directive(pt, 0.8, label="compact_shift")


@controller("hold_line")
def hold_line(ctx: ControllerCtx, player: int, params: dict, mem: dict) -> Directive:
    height = float(params["height"])
    ev = params.get("step_up_on")
    if ev and ctx.ev.play_start_tick is not None and ctx.view.state.events.happened(
            ctx.view.team, ev, ctx.ev.play_start_tick):
        height += 10.0
    return Directive(_line_slot(ctx, player, height, 40.0, 0.5), 0.8, label="hold_line")


@controller("set_position")
def set_position(ctx: ControllerCtx, player: int, params: dict, mem: dict) -> Directive:
    v = ctx.view
    to_ball = v.ball - OWN_GOAL
    dist = float(np.hypot(*to_ball))
    off = min(6.0, dist * 0.25) if params["mode"] == "cover_line" else min(16.0, dist * 0.4)
    pt = OWN_GOAL + _unit(to_ball) * max(off, 1.0)
    return Directive(clip_pitch(pt), 0.8, label="set_position")
