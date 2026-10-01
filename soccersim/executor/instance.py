"""PlayInstance — a play definition bound to players and running (spec §5).

``PlayInstance`` = play + frozen side + role -> player binding + step state machine.
Each tick :meth:`PlayInstance.tick` checks abort, success, the time limit and possession
change, advances the current step, and returns a :class:`Directive` for every bound
player that has an action.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..controllers import REGISTRY, ControllerCtx, Directive
from ..dashboard.evaluator import Evaluator
from ..dashboard.team_state import TeamView
from ..schema.models import Action, Play
from ..schema.vocab import POSSESSION_PHASES

END_REASONS = ("success", "abort", "timeout", "step_timeout_abort", "preempted", "possession_change", "completed")


@dataclass
class ActiveAction:
    action: Action
    players: list[int]
    role: str
    mem: dict[int, dict[str, Any]] = field(default_factory=dict)

    def params(self) -> dict[str, Any]:
        return {**self.action.params, "_type": self.action.type}


class PlayInstance:
    def __init__(self, play: Play, team: int, side: float, binding: dict[str, list[int]], view: TeamView,
                 score: float = 0.0, components: dict | None = None, decision_id: str = "") -> None:
        self.play = play
        self.team = team
        self.side = side
        self.binding = binding
        self.score = score
        self.components = components or {}
        self.decision_id = decision_id
        self.t_start = view.t
        self.tick_start = view.tick
        self.step_idx = 0
        self.step_eligible_t = view.t
        self.step_eligible_tick = view.tick
        self.step_start_t: float | None = None
        self.step_start_tick: int | None = None
        self.actions: dict[str, ActiveAction] = {}
        self.dynamic: dict[str, ActiveAction] = {}
        self.frozen: dict[str, np.ndarray] = {}
        self.steps_visited: list[str] = []
        self.role_targets: dict[str, np.ndarray] = {}
        self.ended = False
        self.end_reason = ""
        self.t_end: float | None = None
        self.epv_start = view.epv()
        self.epv_end: float | None = None
        self.labels: dict[int, str] = {}
        for role, players in binding.items():
            for p in players:
                self.labels[p] = role

    # -- helpers -----------------------------------------------------------------------------

    @property
    def step(self):
        return self.play.steps[self.step_idx]

    @property
    def bound_players(self) -> set[int]:
        return {p for ps in self.binding.values() for p in ps}

    def evaluator(self, view: TeamView, level: str = "step", actor: int = -1) -> Evaluator:
        default_tick = self.tick_start if level == "play" else (
            self.step_start_tick if self.step_start_tick is not None else self.step_eligible_tick)
        return Evaluator(
            view, self.binding, self.side,
            play_start_tick=self.tick_start, step_start_tick=self.step_start_tick,
            play_start_t=self.t_start,
            step_start_t=self.step_start_t if self.step_start_t is not None else self.step_eligible_t,
            event_default_tick=default_tick, frozen=self.frozen, actor=actor,
        )

    def end(self, reason: str, view: TeamView) -> None:
        if self.ended:
            return
        self.ended = True
        self.end_reason = reason
        self.t_end = view.t
        self.epv_end = view.epv()

    # -- the tick -----------------------------------------------------------------------------

    def tick(self, view: TeamView) -> dict[int, Directive]:
        if self.ended:
            return {}
        ev = self.evaluator(view, "play")
        if ev.pred(self.play.abort):
            self.end("abort", view)
            return {}
        if ev.pred(self.play.success):
            self.end("success", view)
            return {}
        if view.t - self.t_start > self.play.max_duration_s:
            self.end("timeout", view)
            return {}
        if self.play.phase in POSSESSION_PHASES and view.possession == "them":
            self.end("possession_change", view)
            return {}
        if self.play.phase not in POSSESSION_PHASES and view.possession == "us" and view.holder >= 0:
            self.end("possession_change", view)
            return {}

        step = self.step
        sev = self.evaluator(view)
        if self.step_start_tick is None:
            if step.start_when is None or sev.pred(step.start_when):
                self._start_step(view)
                sev = self.evaluator(view)
            elif self._timed_out(view):
                self._on_timeout(view)
                return {}
            else:
                return self._directives(view)

        directives = self._directives(view)
        if sev.pred(step.done_when):
            self._advance(view, step.next)
        elif self._timed_out(view):
            self._on_timeout(view)
        return directives

    def _timed_out(self, view: TeamView) -> bool:
        ts = self.step.timeout_s
        return ts is not None and view.t - self.step_eligible_t >= ts

    def _start_step(self, view: TeamView) -> None:
        step = self.step
        self.step_start_t = view.t
        self.step_start_tick = view.tick
        self.frozen.clear()
        self.steps_visited.append(step.id)
        if step.choose is not None:
            ev = self.evaluator(view)
            actions: list[Action] = []
            for opt in step.choose:
                if ev.pred(opt.when):
                    actions = list(opt.actions)
                    break
        else:
            actions = list(step.actions or [])
        for a in actions:
            self._issue(a, view)

    def _issue(self, a: Action, view: TeamView) -> None:
        if a.role is not None:
            players = self.binding.get(a.role, [])
            self.actions[a.role] = ActiveAction(a, list(players), a.role)
            return
        if a.actor == "ball_holder":
            h = view.holder
            if h < 0:
                return
            role = next((r for r, ps in self.binding.items() if h in ps), "ball_holder")
            self.dynamic["ball_holder"] = ActiveAction(a, [h], role)
            return
        group = a.actor["nearest_to_ball_in"]
        members = self.binding.get(group, [])
        if not members:
            return
        d = np.linalg.norm(view.pos[members] - view.ball, axis=1)
        p = members[int(np.argmin(d))]
        self.dynamic[f"nearest:{group}"] = ActiveAction(a, [p], group)

    def _advance(self, view: TeamView, nxt: str | None) -> None:
        if nxt == "end":
            idx = len(self.play.steps)
        elif nxt is not None:
            idx = self.play.step_index(nxt)
        else:
            idx = self.step_idx + 1
        if idx >= len(self.play.steps):
            ev = self.evaluator(view, "play")
            self.end("success" if ev.pred(self.play.success) else "completed", view)
            return
        self.step_idx = idx
        self.step_eligible_t = view.t
        self.step_eligible_tick = view.tick
        self.step_start_t = None
        self.step_start_tick = None
        # Dynamic actors are bound per step.
        self.dynamic.clear()

    def _on_timeout(self, view: TeamView) -> None:
        ot = self.step.on_timeout
        if ot == "abort":
            self.end("step_timeout_abort", view)
        elif ot == "next":
            self._advance(view, self.step.next)
        else:
            self._advance(view, ot.split(":", 1)[1])

    def _directives(self, view: TeamView) -> dict[int, Directive]:
        out: dict[int, Directive] = {}
        ev = self.evaluator(view)
        marked: set[int] = set()
        for bucket in (self.actions, self.dynamic):
            for aa in bucket.values():
                fn = REGISTRY[aa.action.type]
                group = self.binding.get(aa.role, []) if self.play_role_is_group(aa.role) else []
                ctx = ControllerCtx(view, ev, view.ctx.sim, aa.role, group, marked, self.role_targets)
                for p in aa.players:
                    mem = aa.mem.setdefault(p, {})
                    if mem.get("done"):
                        out[p] = Directive(view.pos[p].copy(), 0.0, label="hold")
                        continue
                    ev.actor = p
                    d = fn(ctx, p, aa.params(), mem)
                    out[p] = d
                    self.role_targets[aa.role] = d.target
        return out

    def play_role_is_group(self, role: str) -> bool:
        try:
            return self.play.role(role).group is not None
        except KeyError:
            return False

    # -- logging ------------------------------------------------------------------------------

    def summary(self) -> dict[str, Any]:
        return {
            "play_id": self.play.id,
            "source": self.play.source,
            "team": self.team,
            "side": self.side,
            "binding": {r: list(map(int, ps)) for r, ps in self.binding.items()},
            "t_start": round(self.t_start, 2),
            "t_end": round(self.t_end, 2) if self.t_end is not None else None,
            "duration_s": round((self.t_end or self.t_start) - self.t_start, 2),
            "end_reason": self.end_reason,
            "steps_visited": list(self.steps_visited),
            "epv_start": self.epv_start,
            "epv_end": self.epv_end,
            "score": self.score,
        }
