"""Module 1 dashboard for one team at one tick, in that team's attacking frame (spec §8).

A :class:`TeamView` is cheap to build and computes each geometry layer lazily, caching
it for the tick: pitch control, xT, lines, pass-lane probabilities, EPV. It is also the
``TeamObservation`` handed to policies (spec §7.6).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property

import numpy as np

from ..config import load_config
from ..sim import shots as shots_mod
from ..sim.passmodel import AIR_STYLES, PassAssessment, assess_pass, passer_pressure
from ..sim.physics import max_speed
from ..sim.state import CAP_INDEX, DIRECTION, N_PER_TEAM, MatchState
from .lines import line_height, team_lines
from .pitch_control import pitch_control
from .xt import XTSurface, load_xt
from .zones import GRID_POINTS, zone_mask

KIND_HINT = {"GK": "GK", "DM": "DM", "CM": "CM", "AM": "AM", "ST": "ST"}


@dataclass
class Context:
    """Configs and surfaces shared by every view in a match."""

    sim: dict = field(default_factory=lambda: load_config("sim"))
    formations: dict = field(default_factory=lambda: load_config("formations"))
    xt: XTSurface = field(default_factory=load_xt)
    pc_sharpness: float = 1.5
    possession_term: float = 0.01


class TeamView:
    def __init__(self, state: MatchState, team: int, ctx: Context, opponent_model=None,
                 active_plays: dict | None = None) -> None:
        self.state = state
        self.team = team
        self.ctx = ctx
        self.d = DIRECTION[team]
        self.pos = self.d * state.pos
        self.vel = self.d * state.vel
        self.ball = self.d * state.ball.pos
        self.ball_vel = self.d * state.ball.vel
        self.us = np.arange(team * N_PER_TEAM, (team + 1) * N_PER_TEAM)
        self.them = np.arange((1 - team) * N_PER_TEAM, (2 - team) * N_PER_TEAM)
        self.owner = state.ball.owner
        self.t = state.t
        self.tick = state.tick
        self.opponent_model = opponent_model
        self.active_plays = active_plays or {}

    # -- basic facts -------------------------------------------------------------------

    def is_ours(self, player: int) -> bool:
        return player >= 0 and (player // N_PER_TEAM) == self.team

    @property
    def holder(self) -> int:
        return self.owner if self.is_ours(self.owner) else -1

    @property
    def opp_holder(self) -> int:
        return self.owner if self.owner >= 0 and not self.is_ours(self.owner) else -1

    @property
    def possession(self) -> str:
        p = self.state.possession
        if p is None:
            return "loose"
        return "us" if p == self.team else "them"

    @property
    def minute(self) -> float:
        return self.state.minute

    @property
    def score_diff(self) -> int:
        return self.state.score[self.team] - self.state.score[1 - self.team]

    def outfield(self, idx: np.ndarray) -> np.ndarray:
        return np.array([i for i in idx if self.state.kinds[i] != "GK"], dtype=int)

    @cached_property
    def vmax(self) -> np.ndarray:
        return max_speed(self.state, self.ctx.sim)

    def cap(self, player: int, name: str) -> float:
        return float(self.state.caps[player, CAP_INDEX[name]])

    # -- side and hints ------------------------------------------------------------------

    def side_from_ball(self) -> float:
        """Frozen-side rule (spec §3): sign of ball y, or the emptier side if central."""
        by = self.ball[1]
        if abs(by) >= 2.0:
            return float(np.sign(by))
        band_opps = self.pos[self.them]
        near = np.abs(band_opps[:, 0] - self.ball[0]) < 17.5
        left = int(np.sum(near & (band_opps[:, 1] > 0)))
        right = int(np.sum(near & (band_opps[:, 1] < 0)))
        return 1.0 if left <= right else -1.0

    def hint_of(self, player: int, side: float) -> str:
        """Side-relative position hint of one of our players (spec §3.6)."""
        kind = self.state.kinds[player]
        if kind in KIND_HINT:
            return KIND_HINT[kind]
        base_y = self.state.base_out[player, 1]
        near = base_y * side > 0.5
        return f"{kind}_{'near' if near else 'far'}"

    # -- geometry layer ---------------------------------------------------------------------

    def pc(self, points: np.ndarray) -> np.ndarray:
        """Our pitch control at arbitrary frame points."""
        return pitch_control(
            points, self.pos[self.us], self.vel[self.us], self.vmax[self.us],
            self.pos[self.them], self.vel[self.them], self.vmax[self.them],
            self.ctx.sim["pass"]["reaction_time"], self.ctx.pc_sharpness,
        )

    @cached_property
    def pc_grid(self) -> np.ndarray:
        return self.pc(GRID_POINTS)

    def pc_at(self, point: np.ndarray) -> float:
        return float(self.pc(np.atleast_2d(point))[0])

    @cached_property
    def xt_grid(self) -> np.ndarray:
        return self.ctx.xt.value(GRID_POINTS)

    def xt(self, points):
        return self.ctx.xt.value(points)

    @cached_property
    def lines(self) -> dict[str, float]:
        us = self.outfield(self.us)
        them = self.outfield(self.them)
        return team_lines(self.pos[us, 0], self.pos[them, 0])

    def line_x(self, name: str) -> float:
        return self.lines[name]

    def line_height(self, name: str) -> float:
        return line_height(name, self.lines[name])

    @cached_property
    def offside_x(self) -> float:
        xs = np.sort(self.pos[self.them, 0])
        second_last = xs[-2] if len(xs) >= 2 else 52.5
        return float(max(second_last, self.ball[0], 0.0))

    def onside(self, player: int) -> bool:
        return bool(self.pos[player, 0] <= self.offside_x + 1e-6)

    def nearest_opponent_dist(self, player: int) -> float:
        other = self.them if self.is_ours(player) else self.us
        return float(np.min(np.linalg.norm(self.pos[other] - self.pos[player], axis=1)))

    def pass_assess(self, passer: int, target: np.ndarray, style: str = "ground",
                    receiver: int = -1) -> PassAssessment:
        opp = self.them if self.is_ours(passer) else self.us
        origin = self.pos[passer] if passer >= 0 else self.ball
        return assess_pass(
            origin, np.asarray(target, float), style, self.pos[opp], self.vel[opp], self.vmax[opp], self.ctx.sim,
            receiver_pos=self.pos[receiver] if receiver >= 0 else None,
            receiver_vmax=float(self.vmax[receiver]) if receiver >= 0 else 8.0,
            receiver_aerial=self.cap(receiver, "aerial") if receiver >= 0 else 0.5,
            opp_aerial=self.state.caps[opp, CAP_INDEX["aerial"]] if style in AIR_STYLES else None,
        )

    def pass_p(self, passer: int, target: np.ndarray, style: str = "ground", receiver: int = -1) -> float:
        return self.pass_assess(passer, target, style, receiver).p_success

    @cached_property
    def lane_probs(self) -> dict[int, float]:
        """Ball holder -> each teammate pass success (spec §8.4)."""
        h = self.holder
        if h < 0:
            return {}
        return {int(i): self.pass_p(h, self.pos[i], "ground", int(i)) for i in self.us if i != h}

    @cached_property
    def opp_lane_probs(self) -> dict[int, float]:
        """Opponent carrier -> each of their teammates (for receiver selectors)."""
        h = self.opp_holder
        src = h if h >= 0 else int(self.them[np.argmin(np.linalg.norm(self.pos[self.them] - self.ball, axis=1))])
        return {int(i): self.pass_p(src, self.pos[i], "ground", int(i)) for i in self.them if i != src}

    def xg_of(self, player: int) -> float:
        if player < 0:
            return 0.0
        pos = self.pos[player] if self.is_ours(player) else -self.pos[player]
        opp = self.them if self.is_ours(player) else self.us
        pressure = passer_pressure(self.pos[player], self.pos[opp])
        return float(shots_mod.xg(pos, pressure, False, self.ctx.sim))

    def count_in_zone(self, idx: np.ndarray, zone: str, side: float) -> int:
        return int(np.sum(zone_mask(self.pos[idx], zone, side)))

    # -- value ---------------------------------------------------------------------------

    def epv(self) -> float:
        """EPV proxy: PC-weighted xT at the ball plus a possession term (spec §8.4).

        Positive when the ball is ours and dangerous; negative when theirs.
        """
        term = self.ctx.possession_term
        if self.possession == "us":
            return self.pc_at(self.ball) * float(self.xt(self.ball)) + term
        if self.possession == "them":
            their_ball = -self.ball
            return -((1.0 - self.pc_at(self.ball)) * float(self.xt(their_ball)) + term)
        return 0.0

    # -- serialisation ------------------------------------------------------------------------

    def compact(self) -> dict:
        """Compact serialised dashboard for logs (spec §13 ``state``)."""
        return {
            "t": round(self.t, 2),
            "team": self.team,
            "pos": np.round(self.pos, 2).tolist(),
            "vel": np.round(self.vel, 2).tolist(),
            "stamina": np.round(self.state.stamina, 3).tolist(),
            "kinds": self.state.kinds,
            "base_y": np.round(self.state.base_out[:, 1], 1).tolist(),
            "ball": np.round(self.ball, 2).tolist(),
            "ball_vel": np.round(self.ball_vel, 2).tolist(),
            "owner": int(self.owner),
            "possession": self.possession,
            "lines": {k: round(v, 2) for k, v in self.lines.items()},
            "pc_mean_final_third": round(float(self.pc_grid[GRID_POINTS[:, 0] > 17.5].mean()), 4),
            "epv": round(self.epv(), 5),
            "score_diff": self.score_diff,
            "minute": round(self.minute, 2),
            "team_order": self.team,
        }
