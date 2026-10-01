"""Predicate, target, anchor and selector evaluation against a :class:`TeamView` (spec §3, §4.5, §8.5).

One :class:`Evaluator` is built per (team, play instance, tick). It knows the role
binding, the frozen side, the play/step clocks for event windows, and a ``frozen`` map
for ``freeze: step_start`` anchors that the executor clears at each step start.
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np

from .team_state import TeamView
from .zones import GRID_POINTS, grid_mask, in_zones, lane_center, zone_centroid, zone_mask

NEAR_POST_Y = 3.66


def compare(value: float | None, body: dict) -> bool:
    if value is None:
        return False
    ok = True
    if "lt" in body:
        ok &= value < body["lt"]
    if "le" in body:
        ok &= value <= body["le"]
    if "gt" in body:
        ok &= value > body["gt"]
    if "ge" in body:
        ok &= value >= body["ge"]
    if "eq" in body:
        ok &= abs(value - body["eq"]) < 1e-9
    return bool(ok)


def _key(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, default=str)


class Evaluator:
    def __init__(
        self,
        view: TeamView,
        binding: dict[str, list[int]] | None = None,
        side: float | None = None,
        *,
        play_start_tick: int | None = None,
        step_start_tick: int | None = None,
        play_start_t: float | None = None,
        step_start_t: float | None = None,
        event_default_tick: int | None = None,
        frozen: dict[str, np.ndarray] | None = None,
        actor: int = -1,
    ) -> None:
        self.v = view
        self.binding = binding or {}
        self.side = side if side is not None else view.side_from_ball()
        self.play_start_tick = play_start_tick
        self.step_start_tick = step_start_tick
        self.play_start_t = play_start_t
        self.step_start_t = step_start_t
        self.event_default_tick = event_default_tick
        self.frozen = frozen if frozen is not None else {}
        self.actor = actor
        self.marked: set[int] = set()
        self._dt = view.ctx.sim["tick_s"]

    # -- roles -------------------------------------------------------------------------------

    def player(self, role: str) -> int:
        ps = self.binding.get(role)
        return ps[0] if ps else -1

    def players(self, role: str) -> list[int]:
        return list(self.binding.get(role, []))

    # -- selectors ---------------------------------------------------------------------------

    def _opp_nearest(self, point: np.ndarray, pool: np.ndarray | None = None) -> int:
        pool = self.v.them if pool is None else pool
        if len(pool) == 0:
            return -1
        return int(pool[np.argmin(np.linalg.norm(self.v.pos[pool] - point, axis=1))])

    def selector(self, sel: str) -> int:
        v = self.v
        if sel == "ball_carrier":
            return v.opp_holder if v.opp_holder >= 0 else self._opp_nearest(v.ball)
        if sel == "nearest_to_ball":
            return self._opp_nearest(v.ball)
        if sel.startswith("nearest_to_role:"):
            p = self.player(sel.split(":", 1)[1])
            return self._opp_nearest(v.pos[p]) if p >= 0 else -1
        if sel in ("nearest_receiver", "second_receiver"):
            ranked = sorted(v.opp_lane_probs.items(), key=lambda kv: -kv[1])
            carrier = self.selector("ball_carrier")
            ranked = [i for i, _ in ranked if i != carrier]
            k = 0 if sel == "nearest_receiver" else 1
            return ranked[k] if len(ranked) > k else -1
        if sel.startswith("in_zone:"):
            zone = sel.split(":", 1)[1]
            pool = v.them[zone_mask(v.pos[v.them], zone, self.side)]
            return self._opp_nearest(v.ball, pool)
        if sel == "most_dangerous":
            pool = [i for i in v.outfield(v.them) if i not in self.marked]
            if not pool:
                return -1
            threat = v.xt(-v.pos[pool])
            return int(pool[int(np.argmax(threat))])
        raise ValueError(f"unknown selector {sel!r}")

    # -- anchors and refs ----------------------------------------------------------------------

    def anchor(self, name: str) -> np.ndarray | None:
        v = self.v
        s = self.side
        if name == "ball":
            return v.ball.copy()
        if name == "ball_holder":
            h = v.owner
            return v.pos[h].copy() if h >= 0 else v.ball.copy()
        if name == "goal":
            return np.array([52.5, 0.0])
        if name == "own_goal":
            return np.array([-52.5, 0.0])
        if name == "near_post":
            return np.array([52.5, NEAR_POST_Y * s])
        if name == "far_post":
            return np.array([52.5, -NEAR_POST_Y * s])
        if name == "penalty_spot":
            return np.array([41.5, 0.0])
        if name == "byline_near":
            return np.array([52.5, s * float(np.clip(v.ball[1] * s, 9.0, 30.0))])
        if name.startswith("role:"):
            p = self.player(name[5:])
            return v.pos[p].copy() if p >= 0 else None
        if name.startswith("opp:"):
            p = self.selector(name[4:])
            return v.pos[p].copy() if p >= 0 else None
        if name.startswith("line:"):
            return np.array([v.line_x(name[5:]), v.ball[1]])
        raise ValueError(f"unknown anchor {name!r}")

    def ref_player(self, ref: str) -> int:
        v = self.v
        if ref == "ball_holder":
            return v.holder
        if ref == "ball":
            return v.owner
        if ref.startswith("role:"):
            return self.player(ref[5:])
        if ref.startswith("opp:"):
            return self.selector(ref[4:])
        if ref.startswith("anchor:"):
            return self.ref_player(ref[7:]) if ref[7:].startswith(("role:", "opp:")) else -1
        return -1

    def ref_point(self, ref: str) -> np.ndarray | None:
        if ref.startswith("anchor:"):
            return self.anchor(ref[7:])
        if ref in ("ball", "ball_holder") or ref.startswith(("role:", "opp:", "line:")):
            return self.anchor(ref)
        raise ValueError(f"unknown ref {ref!r}")

    # -- targets -------------------------------------------------------------------------------

    def _region_mask(self, region: dict) -> np.ndarray:
        if "zone" in region:
            return grid_mask(region["zone"], self.side)
        centre = self.anchor(region["anchor"])
        if centre is None:
            return np.zeros(len(GRID_POINTS), dtype=bool)
        m = np.linalg.norm(GRID_POINTS - centre, axis=1) <= region["radius"]
        if not m.any():
            m[np.argmin(np.linalg.norm(GRID_POINTS - centre, axis=1))] = True
        return m

    def _best_point(self, mask: np.ndarray, score: str) -> np.ndarray:
        if not mask.any():
            return self.v.ball.copy()
        vals = self.v.pc_grid.copy()
        if score == "pc_xt":
            vals = vals * self.v.xt_grid
        vals = np.where(mask, vals, -np.inf)
        return GRID_POINTS[int(np.argmax(vals))].copy()

    def target(self, t: dict) -> tuple[np.ndarray | None, int]:
        """Resolve a target to ``(point, player)``; ``player`` is the receiver or opponent, or -1."""
        if "freeze" in t:
            k = _key(t)
            if k not in self.frozen:
                pt, who = self._target(t)
                self.frozen[k] = pt
                return pt, who
            return self.frozen[k], -1
        return self._target(t)

    def _target(self, t: dict) -> tuple[np.ndarray | None, int]:
        v = self.v
        if "role" in t:
            p = self.player(t["role"])
            if p < 0:
                return None, -1
            lead = float(t.get("lead", 0.0))
            vel = v.vel[p]
            sp = float(np.hypot(*vel))
            direction = vel / sp if sp > 1.0 else np.array([1.0, 0.0])
            return v.pos[p] + lead * direction, p
        if "anchor" in t:
            a = self.anchor(t["anchor"])
            if a is None:
                return None, -1
            dx, dy = t.get("offset", [0.0, 0.0])
            pt = a + np.array([dx, dy * self.side])
            pt[0] = np.clip(pt[0], -52.0, 52.0)
            pt[1] = np.clip(pt[1], -33.5, 33.5)
            return pt, -1
        if "zone" in t:
            if t.get("pick") == "centroid":
                return zone_centroid(t["zone"], self.side), -1
            return self._best_point(grid_mask(t["zone"], self.side), "pc"), -1
        if "pc_best" in t:
            return self._best_point(self._region_mask(t["pc_best"]), t.get("score", "pc")), -1
        if "space_behind" in t:
            sb = t["space_behind"]
            x = min(v.line_x(sb["line"]) + sb["depth"], 50.5)
            return np.array([x, lane_center(sb["lane"], self.side)]), -1
        if "best_teammate" in t:
            return self._best_teammate(t["best_teammate"])
        if "opponent" in t:
            p = self.selector(t["opponent"])
            return (v.pos[p].copy(), p) if p >= 0 else (None, -1)
        raise ValueError(f"unknown target {t!r}")

    def _best_teammate(self, spec: dict) -> tuple[np.ndarray | None, int]:
        v = self.v
        src = v.holder if v.holder >= 0 else self.actor
        pool = [int(i) for i in v.outfield(v.us) if i != src]
        if "zone" in spec:
            zoned = [i for i in pool if zone_mask(v.pos[i], spec["zone"], self.side)[0]]
            pool = zoned or pool
        if not pool:
            return None, -1
        probs = np.array([v.lane_probs.get(i) if v.holder >= 0 and i in v.lane_probs
                          else (v.pass_p(src, v.pos[i], "ground", i) if src >= 0 else 0.5) for i in pool])
        pts = v.pos[pool]
        score = spec["score"]
        if score == "pass_p":
            vals = probs
        elif score == "xt":
            vals = v.xt(pts) * np.clip(probs / 0.5, 0.0, 1.0)
        else:
            vals = v.pc(pts) * v.xt(pts) * probs
        best = pool[int(np.argmax(vals))]
        return v.pos[best].copy(), best

    # -- predicates ------------------------------------------------------------------------------

    def _event_since(self, body) -> tuple[str, int]:
        if isinstance(body, str):
            tick = self.event_default_tick if self.event_default_tick is not None else self.v.tick
            return body, tick
        within = body.get("within_s")
        if within is None:
            tick = self.event_default_tick if self.event_default_tick is not None else self.v.tick
        else:
            tick = self.v.tick - int(round(within / self._dt))
        return body["type"], tick

    def pred(self, p: Any) -> bool:
        if p == "always":
            return True
        if not isinstance(p, dict):
            raise ValueError(f"bad predicate {p!r}")
        (key, body), = p.items()
        v = self.v
        if key == "all":
            return all(self.pred(x) for x in body)
        if key == "any":
            return any(self.pred(x) for x in body)
        if key == "not":
            return not self.pred(body)
        if key == "possession":
            return v.possession == body
        if key == "has_ball":
            if body == "teammate":
                return v.holder >= 0
            if body == "opponent":
                return v.opp_holder >= 0
            p_ = self.player(body)
            return p_ >= 0 and v.owner == p_
        if key == "ball_in_zone":
            return bool(in_zones(v.ball[None, :], body, self.side)[0])
        if key == "role_in_zone":
            p_ = self.player(body["role"])
            return p_ >= 0 and bool(zone_mask(v.pos[p_], body["zone"], self.side)[0])
        if key == "dist":
            a, b = self.ref_point(body["a"]), self.ref_point(body["b"])
            if a is None or b is None:
                return False
            return compare(float(np.hypot(*(a - b))), body)
        if key == "ahead_of":
            a, b = self.ref_point(body["a"]), self.ref_point(body["b"])
            if a is None or b is None:
                return False
            return bool(a[0] - b[0] >= body.get("by", 0.0))
        if key == "pressure_on":
            p_ = self.ref_player(body["ref"])
            if p_ < 0:
                return False
            return compare(v.nearest_opponent_dist(p_), body)
        if key == "lane_open":
            src = v.holder if body["from"] == "ball_holder" else self.player(body["from"])
            if src < 0:
                return False
            pt, recv = self.target(body["to"])
            if pt is None:
                return False
            style = "through" if "space_behind" in body["to"] else "ground"
            if recv == src:
                return False
            return v.pass_p(src, pt, style, recv) >= body["min_p"]
        if key == "pc_at":
            pt, _ = self.target(body["target"])
            return pt is not None and compare(v.pc_at(pt), body)
        if key == "xg":
            p_ = self.ref_player(body["ref"])
            return p_ >= 0 and compare(v.xg_of(p_), body)
        if key == "line_height":
            return compare(v.line_height(body["line"]), body)
        if key == "count_in_zone":
            idx = v.us if body["team"] == "us" else v.them
            return compare(v.count_in_zone(idx, body["zone"], self.side), body)
        if key == "goal_side_count":
            if body["team"] == "them":
                of = v.outfield(v.them)
                n = int(np.sum(v.pos[of, 0] > v.ball[0]))
            else:
                of = v.outfield(v.us)
                n = int(np.sum(v.pos[of, 0] < v.ball[0]))
            return compare(n, body)
        if key == "teammates_near":
            c = self.ref_point(body["ref"])
            if c is None:
                return False
            rp = self.ref_player(body["ref"])
            d = np.linalg.norm(v.pos[v.us] - c, axis=1)
            n = int(np.sum((d <= body["radius"]) & (v.us != rp)))
            return compare(n, body)
        if key == "onside":
            p_ = self.player(body)
            return p_ >= 0 and v.onside(p_)
        if key == "event":
            etype, since = self._event_since(body)
            return v.state.events.happened(v.team, etype, since)
        if key == "ball_beyond_line":
            return bool(v.ball[0] > v.line_x(body["line"]) + body.get("by", 0.0))
        if key == "ball_behind_line":
            return bool(v.ball[0] < v.line_x(body["line"]) - body.get("by", 0.0))
        if key == "elapsed_s":
            return compare(v.t - self.play_start_t if self.play_start_t is not None else 0.0, body)
        if key == "step_elapsed_s":
            return compare(v.t - self.step_start_t if self.step_start_t is not None else 0.0, body)
        if key == "game":
            ok = True
            if "score_diff" in body:
                ok &= compare(v.score_diff, body["score_diff"])
            if "minute" in body:
                ok &= compare(v.minute, body["minute"])
            return bool(ok)
        raise ValueError(f"unknown predicate {key!r}")
