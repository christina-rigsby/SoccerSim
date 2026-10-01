"""Off-ball controllers: runs, overlaps, support positions, width."""

from __future__ import annotations

import numpy as np

from ..dashboard.zones import lane_center
from .base import ControllerCtx, Directive, arrived, clip_pitch, controller, hold, move_target, speed_of

DELIVERY_FLIGHT_S = 0.8


def _run(ctx: ControllerCtx, player: int, pt: np.ndarray | None, speed: float, mem: dict, label: str,
         complete: bool = True) -> Directive:
    if pt is None:
        return hold(ctx, player, label)
    if complete and arrived(ctx, player, pt):
        mem["done"] = True
        return hold(ctx, player, label)
    return Directive(clip_pitch(pt), speed, label=label)


@controller("run_to")
def run_to(ctx: ControllerCtx, player: int, params: dict, mem: dict) -> Directive:
    pt, _ = move_target(ctx, player, params["to"], mem)
    speed = speed_of(params, "fast")
    other = params.get("arrive_with")
    if pt is not None and other:
        # Time the run to arrive with the delivery: scale speed so our arrival matches
        # the partner reaching its own target plus the ball's flight.
        partner = ctx.ev.player(other)
        ptarget = ctx.role_targets.get(other)
        if partner >= 0 and ptarget is not None:
            v = ctx.view
            t_deliver = float(np.hypot(*(ptarget - v.pos[partner]))) / max(v.vmax[partner] * 0.8, 1.0)
            t_deliver += DELIVERY_FLIGHT_S
            dist = float(np.hypot(*(pt - v.pos[player])))
            want = dist / max(t_deliver, 0.3) / max(v.vmax[player], 1.0)
            speed = float(np.clip(want, 0.45, 1.0))
    return _run(ctx, player, pt, speed, mem, "run_to")


@controller("third_man_run", "decoy_run")
def third_man_run(ctx: ControllerCtx, player: int, params: dict, mem: dict) -> Directive:
    pt, _ = move_target(ctx, player, params["to"], mem)
    return _run(ctx, player, pt, speed_of(params, "fast"), mem, "run")


@controller("hold_position")
def hold_position(ctx: ControllerCtx, player: int, params: dict, mem: dict) -> Directive:
    pt, _ = move_target(ctx, player, params["to"], mem)
    return _run(ctx, player, pt, 0.7, mem, "hold_position")


@controller("overlap", "underlap")
def overlap(ctx: ControllerCtx, player: int, params: dict, mem: dict) -> Directive:
    v = ctx.view
    side = ctx.ev.side
    around = ctx.ev.player(params["around"])
    if around < 0:
        return hold(ctx, player, "overlap")
    under = mem.get("_under")
    if under is None:
        under = mem["_under"] = bool(params.get("_type") == "underlap")
    lateral = -4.0 if under else 4.0
    target = params.get("to") or {"anchor": f"role:{params['around']}", "offset": [10, lateral]}
    pt, _ = move_target(ctx, player, target, mem)
    if pt is None:
        return hold(ctx, player, "overlap")
    speed = speed_of(params, "max")
    if v.pos[player, 0] < v.pos[around, 0] + 1.5:
        # Phase 1: get round the outside (or inside) of the partner.
        way = v.pos[around] + np.array([3.0, lateral * side])
        return Directive(clip_pitch(way), speed, label="underlap" if under else "overlap")
    return _run(ctx, player, pt, speed, mem, "underlap" if under else "overlap")


@controller("spin_in_behind")
def spin_in_behind(ctx: ControllerCtx, player: int, params: dict, mem: dict) -> Directive:
    v = ctx.view
    pt, _ = ctx.ev.target({"space_behind": {"line": params["line"], "lane": params["lane"], "depth": params["depth"]}})
    fl = v.state.ball.flight
    ours_in_flight = fl is not None and fl.team == v.team and fl.kind == "pass"
    if not ours_in_flight:
        # Stay onside until the ball is played: shape the run along the line.
        pt = pt.copy()
        pt[0] = min(pt[0], v.offside_x - 1.0)
        return Directive(clip_pitch(pt), 0.8, label="spin_in_behind")
    return _run(ctx, player, pt, 1.0, mem, "spin_in_behind")


@controller("check_to_ball")
def check_to_ball(ctx: ControllerCtx, player: int, params: dict, mem: dict) -> Directive:
    v = ctx.view
    if "t0" not in mem:
        mem["t0"] = v.t
        start = v.pos[player]
        to_ball = v.ball - start
        dist = float(np.hypot(*to_ball))
        step = min(params["distance"], max(dist - 2.0, 0.0))
        mem["pt"] = start + (to_ball / dist * step if dist > 1e-6 else 0.0)
    if v.t - mem["t0"] >= params["duration_s"]:
        mem["done"] = True
    return Directive(clip_pitch(mem["pt"]), 1.0, label="check_to_ball")


@controller("support")
def support(ctx: ControllerCtx, player: int, params: dict, mem: dict) -> Directive:
    v = ctx.view
    frm = ctx.ev.player(params["from"])
    if frm < 0:
        return hold(ctx, player, "support")
    d = float(params["distance"])
    side = ctx.ev.side
    off = {
        "back_inside": (-0.7 * d, -0.7 * d),
        "back_outside": (-0.7 * d, 0.7 * d),
        "square": (0.0, -d),
        "forward": (d, 0.0),
    }[params["angle"]]
    pt = v.pos[frm] + np.array([off[0], off[1] * side])
    return Directive(clip_pitch(pt, 1.5), 0.75, label="support")


@controller("hold_width")
def hold_width(ctx: ControllerCtx, player: int, params: dict, mem: dict) -> Directive:
    v = ctx.view
    y = lane_center(params["lane"], ctx.ev.side)
    if params["lane"].endswith("wing"):
        y = np.sign(y) * 30.0
    x = min(v.ball[0] + 6.0, v.offside_x - 0.8) if v.possession == "us" else v.pos[player, 0]
    return Directive(clip_pitch(np.array([x, y])), 0.7, label="hold_width")
