"""MatchEnv — ticks the simulator and calls policies at decision points (spec §7.5–7.6).

Each team has at most one active play. Module 2 re-ranks when the active play ends,
possession changes, a restart occurs, or every ``rerank_interval_s`` as an interrupt
(where the policy applies the preemption hysteresis).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Protocol

import numpy as np

from ..config import config_hash, deep_update, load_config
from ..controllers import Directive
from ..dashboard.team_state import Context, TeamView
from ..executor.instance import PlayInstance
from ..executor.runner import team_directives
from .ball import BallCommand, gain_control, release, step_ball
from .duels import foul_prob, tackle_success_prob
from .events import emit
from .physics import step_players
from .restarts import award_restart, execute_restart
from .scenarios import Scenario, build_state, setup_scenario
from .state import DIRECTION, MatchState, team_of, team_players


class Policy(Protocol):
    def decide(self, obs: TeamView, reason: str) -> PlayInstance | None: ...


@dataclass
class EpisodeResult:
    seed: int
    scenario: dict
    score: list[int]
    duration_s: float
    end_cause: str
    plays: list[dict[str, Any]] = field(default_factory=list)       # one per instantiated play, with decision
    decisions: list[dict[str, Any]] = field(default_factory=list)   # every decide() call record
    events: list[dict[str, Any]] = field(default_factory=list)
    frames: list[dict[str, Any]] = field(default_factory=list)      # 10 Hz tracking for the replay viewer
    sim_config_hash: str = ""
    caps: list[list[float]] = field(default_factory=list)
    kinds: list[str] = field(default_factory=list)

    def goals(self, team: int) -> int:
        return self.score[team]


def randomise_sim(cfg: dict, rng: np.random.Generator) -> dict:
    """Domain randomisation (spec §11): reaction time, noise scale, friction."""
    cfg = copy.deepcopy(cfg)
    rz = cfg.get("randomisation", {})
    if "reaction_time" in rz:
        cfg["pass"]["reaction_time"] = float(rng.uniform(*rz["reaction_time"]))
    if "noise_scale" in rz:
        cfg["noise_scale"] = float(rng.uniform(*rz["noise_scale"]))
    if "friction" in rz:
        cfg["ball"]["friction"] = float(rng.uniform(*rz["friction"]))
    return cfg


def held_out_sim(cfg: dict) -> dict:
    """The held-out physics config used for overfitting checks (spec §11)."""
    cfg = copy.deepcopy(cfg)
    ho = cfg.get("held_out", {})
    deep_update(cfg, {k: v for k, v in ho.items() if k != "noise_scale"})
    cfg["noise_scale"] = ho.get("noise_scale", 1.0)
    return cfg


class MatchEnv:
    def __init__(self, sim_cfg: dict | None = None, ctx: Context | None = None, randomise: bool = False,
                 record_frames: bool = True, rerank_interval_s: float | None = None) -> None:
        self.base_cfg = sim_cfg or load_config("sim")
        self.ctx = ctx or Context(sim=self.base_cfg)
        self.randomise = randomise
        self.record_frames = record_frames
        rank = load_config("ranking")
        self.rerank_interval = rerank_interval_s or rank["selection"]["rerank_interval_s"]
        self.state: MatchState | None = None
        self.rng: np.random.Generator = np.random.default_rng(0)
        self.scenario: Scenario | None = None
        self.seed = 0

    # -- reset ---------------------------------------------------------------------------

    def reset(self, seed: int, scenario: Scenario | None = None) -> MatchState:
        self.seed = seed
        self.rng = np.random.default_rng(seed)
        self.scenario = scenario or Scenario()
        cfg = randomise_sim(self.base_cfg, self.rng) if self.randomise else copy.deepcopy(self.base_cfg)
        self.cfg = cfg
        self.ctx.sim = cfg
        self.state = build_state(self.rng, self.scenario, cfg, self.ctx.formations)
        setup_scenario(self.state, self.scenario, self.rng, cfg, self.ctx.formations)
        return self.state

    # -- run -----------------------------------------------------------------------------

    def run(self, home: Policy, away: Policy, max_time_s: float | None = None,
            stop_on_goal: bool = True, stop_on_turnover: bool = True) -> EpisodeResult:
        assert self.state is not None, "call reset() first"
        state = self.state
        cfg = self.cfg
        dt = cfg["tick_s"]
        max_time = max_time_s or cfg["episode"]["max_time_s"]
        grace = cfg["episode"]["possession_change_grace_s"]
        policies = (home, away)
        for p in policies:
            if hasattr(p, "reset"):
                p.reset()
        active: dict[int, PlayInstance | None] = {0: None, 1: None}
        last_decide = [-1e9, -1e9]
        next_try = [0.0, 0.0]
        prev_poss = state.possession
        start_poss = state.possession
        turnover_t: float | None = None
        result = EpisodeResult(self.seed, self.scenario.to_dict(), list(state.score), 0.0, "time_limit",
                               sim_config_hash=config_hash(cfg), caps=np.round(state.caps, 3).tolist(),
                               kinds=list(state.kinds))
        n_events_logged = 0
        restart_fired = False
        end_cause = "time_limit"

        while state.t < max_time - 1e-9:
            # 1. Restarts.
            restart_fired = False
            if state.restart is not None and state.t >= state.restart.ready_t:
                execute_restart(state, cfg)
                restart_fired = True

            views = {tm: TeamView(state, tm, self.ctx, active_plays=active) for tm in (0, 1)}

            # 2. Close finished plays; decide.
            for tm in (0, 1):
                inst = active[tm]
                reason = ""
                if inst is None or inst.ended:
                    reason = "play_end" if inst is not None else "start"
                if state.possession != prev_poss and state.possession is not None:
                    reason = "possession_change"
                if restart_fired:
                    reason = "restart"
                if not reason and state.t - last_decide[tm] >= self.rerank_interval - 1e-9:
                    reason = "interrupt"
                if not reason or state.restart is not None:
                    continue
                if reason in ("start", "play_end") and state.t < next_try[tm]:
                    continue
                new = policies[tm].decide(views[tm], reason)
                last_decide[tm] = state.t
                rec = getattr(policies[tm], "last_decision", None)
                if rec is not None:
                    result.decisions.append(rec)
                if new is not None:
                    if inst is not None and not inst.ended:
                        inst.end("preempted", views[tm])
                        self._close(inst, policies[tm], result, views[tm])
                    new.decision = rec
                    new.state_compact = views[tm].compact()
                    new.opp_play_at_start = active[1 - tm].play.id if active[1 - tm] else None
                    active[tm] = new
                elif inst is None or inst.ended:
                    next_try[tm] = state.t + 0.5

            prev_poss = state.possession

            # 3. Directives.
            targets = state.pos.copy()
            speeds = np.zeros(22)
            modes = ["default"] * 22
            protect = np.zeros(22, dtype=bool)
            ball_cmd: BallCommand | None = None
            for tm in (0, 1):
                v = views[tm]
                dirs = team_directives(v, active[tm])
                if active[tm] is not None and active[tm].ended:
                    self._close(active[tm], policies[tm], result, v)
                    active[tm] = None
                d = DIRECTION[tm]
                for p, dv in dirs.items():
                    targets[p] = d * dv.target
                    speeds[p] = dv.speed
                    modes[p] = dv.mode
                    protect[p] = dv.protect
                    if dv.ball is not None and state.ball.owner == p and ball_cmd is None:
                        ball_cmd = BallCommand(dv.ball.kind, d * dv.ball.target, dv.ball.style, dv.ball.receiver,
                                               dv.ball.placement)
                if self.record_frames:
                    self._frame_labels = getattr(self, "_frame_labels", {})
                    self._frame_labels[tm] = dirs

            # 4. Ball commands, movement, ball, duels.
            if ball_cmd is not None and state.restart is None:
                release(state, ball_cmd, cfg, self.rng)
            step_players(state, targets, np.where(protect, speeds * 0.7, speeds), cfg, dt)
            step_ball(state, cfg, self.rng, dt)
            if state.restart is None and state.ball.owner >= 0:
                self._tackles(state, modes, protect, cfg, dt)

            if self.record_frames:
                self._record_frame(result, active)
            for ev in state.events.events[n_events_logged:]:
                result.events.append(ev.to_dict())
            n_events_logged = len(state.events)

            state.t = round(state.t + dt, 10)
            state.tick += 1

            # 5. Termination.
            if stop_on_goal and any(e["type"] == "goal" for e in result.events[-4:]) and any(
                    e["type"] == "goal" and e["t"] >= state.t - dt - 1e-6 for e in result.events[-4:]):
                end_cause = "goal"
                break
            if state.possession is not None and start_poss is not None and state.possession != start_poss \
                    and turnover_t is None:
                turnover_t = state.t
            if stop_on_turnover and turnover_t is not None and state.t - turnover_t >= grace:
                end_cause = "possession_change"
                break

        views = {tm: TeamView(state, tm, self.ctx, active_plays=active) for tm in (0, 1)}
        for tm in (0, 1):
            if active[tm] is not None and not active[tm].ended:
                active[tm].end("timeout" if end_cause == "time_limit" else end_cause_to_reason(end_cause),
                               views[tm])
                self._close(active[tm], policies[tm], result, views[tm])
        result.score = list(state.score)
        result.duration_s = round(state.t, 2)
        result.end_cause = end_cause
        return result

    # -- internals -------------------------------------------------------------------------

    def _close(self, inst: PlayInstance, policy: Policy, result: EpisodeResult, view: TeamView) -> None:
        if getattr(inst, "_closed", False):
            return
        inst._closed = True
        if hasattr(policy, "notify_end"):
            policy.notify_end(inst, view.t)
        rec = inst.summary()
        rec["decision"] = getattr(inst, "decision", None)
        rec["state"] = getattr(inst, "state_compact", None)
        rec["opp_play_at_start"] = getattr(inst, "opp_play_at_start", None)
        rec["opp_play_at_end"] = view.active_plays.get(1 - inst.team).play.id \
            if view.active_plays.get(1 - inst.team) is not None else None
        rec["events"] = [e.to_dict() for e in view.state.events.since(inst.team, inst.tick_start)]
        rec["play_yaml"] = None if inst.play.source == "library" else inst.play.model_dump(mode="json",
                                                                                          exclude_none=True)
        result.plays.append(rec)

    def _tackles(self, state: MatchState, modes: list[str], protect: np.ndarray, cfg: dict, dt: float) -> None:
        owner = state.ball.owner
        dc = cfg["duel"]
        opp = list(team_players(1 - team_of(owner)))
        d = np.linalg.norm(state.pos[opp] - state.pos[owner], axis=1)
        for k in np.argsort(d):
            j = opp[int(k)]
            if d[k] > dc["tackle_range"]:
                break
            if state.tackle_cooldown[j] > state.t or state.stun_until[j] > state.t:
                continue
            rate = dc["intensity_rate"].get(modes[j], dc["intensity_rate"]["default"])
            if rate <= 0 or self.rng.random() > min(1.0, rate * dt / dc["attempt_interval_s"]):
                continue
            state.tackle_cooldown[j] = state.t + dc["attempt_interval_s"]
            p = tackle_success_prob(state, j, owner, cfg, bool(protect[owner]), modes[j])
            if self.rng.random() < p:
                if self.rng.random() < 0.6:
                    gain_control(state, j, cfg, cause="tackle")
                else:
                    ball = state.ball
                    ang = self.rng.uniform(0, 2 * np.pi)
                    ball.owner = -1
                    ball.vel = np.array([np.cos(ang), np.sin(ang)]) * 4.0
                    ball.last_touch_team = team_of(j)
                    ball.last_touch_player = j
                    state.possession = None
                    state.touch_cooldown[owner] = state.t + 0.5
                    emit(state, "tackle_won", team_of(j), j)
                return
            if self.rng.random() < foul_prob(state, j, owner, cfg):
                carrier_team = team_of(owner)
                emit(state, "foul_won", carrier_team, owner)
                award_restart(state, "free_kick", carrier_team, state.pos[owner].copy(), cfg)
                return
            state.stun_until[j] = state.t + 0.6
            return

    def _record_frame(self, result: EpisodeResult, active: dict[int, PlayInstance | None]) -> None:
        state = self.state
        labels = getattr(self, "_frame_labels", {})
        plays = {}
        for tm in (0, 1):
            inst = active[tm]
            dirs: dict[int, Directive] = labels.get(tm, {})
            d = DIRECTION[tm]
            acts = {int(p): [dv.label, round(float(d * dv.target[0]), 1), round(float(d * dv.target[1]), 1)]
                    for p, dv in dirs.items() if dv.label not in ("shape",)}
            if inst is not None:
                plays[tm] = {
                    "id": inst.play.id, "source": inst.play.source,
                    "step": inst.step.id if not inst.ended else "-",
                    "roles": {int(p): r for p, r in inst.labels.items()},
                }
            else:
                plays[tm] = None
            plays[f"acts{tm}"] = acts
        fl = state.ball.flight
        result.frames.append({
            "t": round(state.t, 2),
            "p": np.round(state.pos, 1).tolist(),
            "b": [round(float(state.ball.pos[0]), 2), round(float(state.ball.pos[1]), 2)],
            "bh": state.ball.height,
            "o": int(state.ball.owner),
            "s": list(state.score),
            "poss": state.possession,
            "fl": None if fl is None else [fl.kind, round(float(fl.target[0]), 1), round(float(fl.target[1]), 1)],
            "plays": plays,
        })


def end_cause_to_reason(cause: str) -> str:
    return {"goal": "success", "possession_change": "possession_change"}.get(cause, "timeout")
