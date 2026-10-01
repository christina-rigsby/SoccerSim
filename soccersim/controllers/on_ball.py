"""On-ball controllers: pass, cross, cutback, carry, dribble, shoot, hold_up, clear, distribute."""

from __future__ import annotations

import numpy as np

from .base import (
    ControllerCtx,
    Directive,
    FrameBallCommand,
    arrived,
    clip_pitch,
    controller,
    hold,
    move_target,
    nearest_teammate_to,
    speed_of,
)

SETTLE_S = 0.3  # a non-one-touch pass waits this long after receiving


def _has_ball(ctx: ControllerCtx, player: int) -> bool:
    return ctx.view.owner == player


def _release(ctx: ControllerCtx, player: int, params: dict, mem: dict, kind: str, style: str, label: str) -> Directive:
    v = ctx.view
    if not _has_ball(ctx, player):
        return hold(ctx, player, label)
    if not params.get("one_touch") and v.t - v.state.ball.owner_since < SETTLE_S:
        return hold(ctx, player, label, protect=True)
    if "to" in params:
        pt, recv = ctx.ev.target(params["to"])
    else:
        pt, recv = None, -1
    if pt is None:
        if kind != "clear":
            return hold(ctx, player, label, protect=True)
        pt = np.array([min(v.ball[0] + 40.0, 30.0), np.sign(v.ball[1] or 1.0) * 24.0])
    pt = clip_pitch(pt, 0.3) if kind != "clear" else pt
    if recv < 0 and kind != "clear":
        recv = nearest_teammate_to(ctx, pt, player)
    if recv == player:
        return hold(ctx, player, label, protect=True)
    mem["done"] = True
    return Directive(v.pos[player].copy(), 0.0, FrameBallCommand(kind, pt, style, recv), label=label)


@controller("pass")
def pass_(ctx: ControllerCtx, player: int, params: dict, mem: dict) -> Directive:
    return _release(ctx, player, params, mem, "pass", params.get("style", "ground"), "pass")


@controller("distribute")
def distribute(ctx: ControllerCtx, player: int, params: dict, mem: dict) -> Directive:
    return _release(ctx, player, params, mem, "pass", params.get("style", "ground"), "distribute")


@controller("cross")
def cross(ctx: ControllerCtx, player: int, params: dict, mem: dict) -> Directive:
    return _release(ctx, player, params, mem, "pass", params.get("style", "lofted"), "cross")


@controller("cutback")
def cutback(ctx: ControllerCtx, player: int, params: dict, mem: dict) -> Directive:
    return _release(ctx, player, {**params, "one_touch": True}, mem, "pass", "ground", "cutback")


@controller("clear")
def clear(ctx: ControllerCtx, player: int, params: dict, mem: dict) -> Directive:
    return _release(ctx, player, {**params, "one_touch": True}, mem, "clear", "clear", "clear")


@controller("shoot")
def shoot(ctx: ControllerCtx, player: int, params: dict, mem: dict) -> Directive:
    v = ctx.view
    if not _has_ball(ctx, player):
        return hold(ctx, player, "shoot")
    mem["done"] = True
    cmd = FrameBallCommand("shoot", np.array([52.5, 0.0]), params.get("style", "placed"), -1,
                           params.get("placement", "auto"))
    return Directive(v.pos[player].copy(), 0.0, cmd, label="shoot")


@controller("carry")
def carry(ctx: ControllerCtx, player: int, params: dict, mem: dict) -> Directive:
    if not _has_ball(ctx, player):
        return hold(ctx, player, "carry")
    pt, _ = move_target(ctx, player, params["to"], mem)
    if pt is None:
        return hold(ctx, player, "carry", protect=True)
    if arrived(ctx, player, pt, 1.5):
        mem["done"] = True
        return hold(ctx, player, "carry", protect=bool(params.get("protect")))
    protect = bool(params.get("protect"))
    speed = speed_of(params, "fast") * (ctx.cfg["movement"]["protect_speed_factor"] / 0.82 if protect else 1.0)
    return Directive(pt, min(speed, 1.0), protect=protect, label="carry")


@controller("dribble")
def dribble(ctx: ControllerCtx, player: int, params: dict, mem: dict) -> Directive:
    v = ctx.view
    if not _has_ball(ctx, player):
        return hold(ctx, player, "dribble")
    pt, _ = move_target(ctx, player, params["to"], mem)
    if pt is None:
        return hold(ctx, player, "dribble", protect=True)
    if arrived(ctx, player, pt, 1.5):
        mem["done"] = True
        return hold(ctx, player, "dribble")
    opp = ctx.ev.selector(params["beat"]) if "beat" in params else ctx.ev.selector("nearest_to_ball")
    aim = pt.copy()
    if opp >= 0:
        rel = v.pos[opp] - v.pos[player]
        heading = pt - v.pos[player]
        dist = float(np.hypot(*rel))
        if 0 < dist < 6.0 and float(np.dot(rel, heading)) > 0:
            # Go around the defender on the side away from them.
            perp = np.array([-heading[1], heading[0]])
            perp /= max(float(np.hypot(*perp)), 1e-6)
            sign = -np.sign(float(np.dot(perp, rel)) or 1.0)
            aim = v.pos[player] + heading / max(float(np.hypot(*heading)), 1e-6) * 4.0 + perp * sign * 3.0
    return Directive(clip_pitch(aim), 1.0, label="dribble")


@controller("hold_up")
def hold_up(ctx: ControllerCtx, player: int, params: dict, mem: dict) -> Directive:
    v = ctx.view
    mem.setdefault("t0", v.t)
    if v.t - mem["t0"] >= params["duration_s"]:
        mem["done"] = True
    if not _has_ball(ctx, player):
        return hold(ctx, player, "hold_up")
    # Shield: drift slightly back toward our own goal.
    return Directive(clip_pitch(v.pos[player] + np.array([-1.0, 0.0])), 0.3, protect=True, label="hold_up")
