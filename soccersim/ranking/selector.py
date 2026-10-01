"""Module 2 policy: candidates -> hard gate -> assignment -> score -> select (spec §9).

:class:`RankingPolicy` is the ``Policy`` of spec §7.6. It also hosts the Module 3 hook:
when the generator is enabled it is consulted either on every decision (``always``) or
only when the library leaves a *gap* (``on_gap``: no feasible non-fallback library play,
or the best library score is under ``threshold``). Generated plays go through exactly
the same trigger check, hard gate, assignment and scoring as library plays and compete
in the same argmax — one selection mechanism, not two (D-001).
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Any, Protocol

import numpy as np

from ..config import load_config
from ..dashboard.evaluator import Evaluator
from ..dashboard.team_state import TeamView
from ..executor.instance import PlayInstance
from ..schema.models import Play
from .assignment import Assignment, assign
from .constraints import hard_gate, in_cooldown, phases_for, triggers_hold
from .scorer import CriticFn, score_play

_ids = itertools.count()


class Generator(Protocol):
    def sample(self, obs: TeamView, n: int) -> list[Play]: ...


@dataclass
class Candidate:
    play: Play
    feasible: bool
    reason: str = ""
    score: float = float("-inf")
    components: dict[str, float] = field(default_factory=dict)
    assignment: Assignment | None = None
    side: float = 1.0

    def record(self) -> dict[str, Any]:
        return {
            "play_id": self.play.id, "source": self.play.source, "feasible": self.feasible,
            "reason": self.reason, "score": round(self.score, 5) if np.isfinite(self.score) else None,
            "components": self.components,
        }


class RankingPolicy:
    def __init__(
        self,
        library: dict[str, Play],
        rng: np.random.Generator | None = None,
        cfg: dict | None = None,
        temperature: float | None = None,
        style: dict[str, float] | None = None,
        generator: Generator | None = None,
        critic: CriticFn | None = None,
        name: str = "library",
    ) -> None:
        self.library = library
        self.rng = rng or np.random.default_rng(0)
        self.cfg = cfg or load_config("ranking")
        self.temperature = self.cfg["selection"]["temperature"] if temperature is None else temperature
        self.style = style or {}
        self.generator = generator
        self.critic = critic
        self.name = name
        self.cooldowns: dict[str, float] = {}
        self.last_decision: dict[str, Any] | None = None
        self.generated_cache: dict[str, Play] = {}

    # -- lifecycle ------------------------------------------------------------------------

    def reset(self) -> None:
        self.cooldowns.clear()

    def notify_end(self, inst: PlayInstance, t: float) -> None:
        if inst.play.cooldown_s > 0:
            self.cooldowns[inst.play.id] = t + inst.play.cooldown_s

    # -- ranking --------------------------------------------------------------------------

    def evaluate(self, play: Play, obs: TeamView, side: float) -> Candidate:
        asg = assign(play, obs, side, self.cfg)
        if not asg.feasible:
            return Candidate(play, False, asg.reason, side=side)
        ev = Evaluator(obs, asg.binding, side, event_default_tick=obs.tick, play_start_t=obs.t, step_start_t=obs.t)
        if not triggers_hold(play, ev):
            return Candidate(play, False, "triggers", assignment=asg, side=side)
        failed = hard_gate(play, ev)
        if failed:
            return Candidate(play, False, failed, assignment=asg, side=side)
        score, comp = score_play(play, obs, asg, self.cfg, self.critic, self.style.get(play.id, 0.0))
        return Candidate(play, True, "", score, comp, asg, side)

    def rank(self, obs: TeamView, plays: list[Play]) -> list[Candidate]:
        phases = phases_for(obs)
        side = obs.side_from_ball()
        out = []
        for play in plays:
            if play.phase not in phases:
                continue
            if in_cooldown(play, self.cooldowns, obs.t):
                out.append(Candidate(play, False, "cooldown", side=side))
                continue
            out.append(self.evaluate(play, obs, side))
        return out

    def _gap(self, cands: list[Candidate]) -> bool:
        real = [c for c in cands if c.feasible and not c.play.fallback]
        if not real:
            return True
        return max(c.score for c in real) < self.cfg["generator"]["threshold"]

    def _select(self, feasible: list[Candidate]) -> Candidate:
        if self.temperature and self.temperature > 0 and len(feasible) > 1:
            s = np.array([c.score for c in feasible]) / self.temperature
            p = np.exp(s - s.max())
            p /= p.sum()
            return feasible[int(self.rng.choice(len(feasible), p=p))]
        return max(feasible, key=lambda c: c.score)

    # -- Policy.decide -------------------------------------------------------------------

    def decide(self, obs: TeamView, reason: str) -> PlayInstance | None:
        active: PlayInstance | None = obs.active_plays.get(obs.team)
        if active is not None and active.ended:
            active = None
        cands = self.rank(obs, list(self.library.values()))
        gcfg = self.cfg["generator"]
        gen_used = False
        gap = self._gap(cands)
        phases = phases_for(obs)
        if (self.generator is not None and gcfg.get("enabled", False)
                and any(ph in gcfg.get("phases", []) for ph in phases)
                and (gcfg.get("activation") == "always" or gap)):
            generated = self.generator.sample(obs, int(gcfg.get("k", 4)))
            gen_used = bool(generated)
            for play in generated:
                self.generated_cache[play.id] = play
            cands += self.rank(obs, generated)
        feasible = [c for c in cands if c.feasible]
        record: dict[str, Any] = {
            "t": round(obs.t, 2), "team": obs.team, "reason": reason, "policy": self.name,
            "candidates": [c.record() for c in cands], "chosen": None, "chosen_source": None,
            "generator_used": gen_used, "library_gap": gap, "kept_active": False,
        }
        self.last_decision = record
        if not feasible:
            return None
        best = self._select(feasible)
        if active is not None:
            if best.play.id == active.play.id:
                record["kept_active"] = True
                return None
            if reason == "interrupt" and best.score - active.score <= self.cfg["selection"]["preempt_margin"]:
                record["kept_active"] = True
                return None
        record["chosen"] = best.play.id
        record["chosen_source"] = best.play.source
        record["chosen_score"] = round(best.score, 5)
        record["chosen_components"] = best.components
        did = f"{obs.team}-{next(_ids)}"
        record["decision_id"] = did
        return PlayInstance(best.play, obs.team, best.side, best.assignment.binding, obs, best.score,
                            best.components, did)


class ForcedPolicy(RankingPolicy):
    """Instantiates one named play whenever it is feasible (optionally ignoring triggers).

    Used by execution tests and for debugging a single play in isolation. Falls back to
    normal ranking once the forced play has run ``times`` times.
    """

    def __init__(self, library: dict[str, Play], play_id: str, ignore_triggers: bool = False, times: int = 1,
                 extra: Play | None = None, **kw) -> None:
        super().__init__(library, **kw)
        self.forced = extra if extra is not None else library[play_id]
        self.ignore_triggers = ignore_triggers
        self.remaining = times

    def reset(self) -> None:
        super().reset()

    def decide(self, obs: TeamView, reason: str) -> PlayInstance | None:
        active = obs.active_plays.get(obs.team)
        if self.remaining > 0 and self.forced.phase in phases_for(obs) and (active is None or active.ended):
            side = obs.side_from_ball()
            asg = assign(self.forced, obs, side, self.cfg)
            if asg.feasible:
                ev = Evaluator(obs, asg.binding, side, event_default_tick=obs.tick)
                if self.ignore_triggers or (triggers_hold(self.forced, ev) and not hard_gate(self.forced, ev)):
                    self.remaining -= 1
                    score, comp = score_play(self.forced, obs, asg, self.cfg)
                    self.last_decision = {"t": round(obs.t, 2), "team": obs.team, "reason": reason,
                                          "policy": "forced", "candidates": [], "chosen": self.forced.id,
                                          "chosen_source": self.forced.source, "generator_used": False,
                                          "library_gap": False, "kept_active": False,
                                          "decision_id": f"{obs.team}-{next(_ids)}"}
                    return PlayInstance(self.forced, obs.team, side, asg.binding, obs, score, comp,
                                        self.last_decision["decision_id"])
        if self.remaining > 0 and active is not None and not active.ended and active.play.id == self.forced.id:
            return None
        return super().decide(obs, reason)
