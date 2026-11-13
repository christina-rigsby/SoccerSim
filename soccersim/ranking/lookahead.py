"""The look-ahead team: try every candidate play from the same moment, then call the best.

At each real decision (a play ended, possession changed, a restart, the start), this policy:

1. ranks the library as usual and keeps the ``top_k`` feasible plays by the hand-written score;
2. for each of them, copies the game exactly as it is (:meth:`MatchEnv.fork`), starts that play
   in the copy, and plays ``horizon_s`` seconds forward, ``rollouts`` times with different random
   seeds. The opponent keeps playing as it normally would (a copy of its own policy), and after
   the tried play ends our team carries on with the plain library ranking;
3. scores each trial from our side: change in EPV (expected-goal value of the position) over
   the horizon, plus 1 per goal for (minus 1 per goal against), plus ``shot_xg`` x the xG of
   our shots (minus theirs) — the same terms as a play's reward (``configs/training.yaml``);
4. calls the play with the best average.

**Common random numbers.** Every candidate is tried with the *same* set of seeds, so the
candidates face the same luck (the same pass errors, the same tackle rolls) as far as their
paths stay alike. Comparing them is then much less noisy than with independent seeds.

Periodic re-checks (``interrupt``, every 2 s) use the plain ranking, with its usual switching
rule, to keep the cost down. The trials of every decision are kept in ``last_decision`` under
``lookahead`` (per play: mean, standard deviation, values), as training data for a critic.

The opponent in the trials is a copy of the real opponent's policy, which a real team could
not know: this team is an upper bound on what better play selection can achieve, not a fair
competitor.
"""

from __future__ import annotations

import copy
from typing import Any

import numpy as np

from ..config import load_config
from ..dashboard.team_state import TeamView
from ..executor.instance import PlayInstance
from ..schema.models import Play
from .selector import Candidate, RankingPolicy

REAL_DECISIONS = ("start", "play_end", "possession_change", "restart")


def fork_policy(policy: Any, seed: int) -> Any:
    """A copy of a policy for a trial: its own random stream and cooldowns, no shared buffers."""
    if hasattr(policy, "fork"):
        return policy.fork(seed)
    q = copy.copy(policy)
    if hasattr(policy, "cooldowns"):
        q.cooldowns = dict(policy.cooldowns)
    if hasattr(policy, "rng"):
        q.rng = np.random.default_rng(seed)
    if hasattr(policy, "rollout_buffer"):
        q.rollout_buffer = []
    q.last_decision = None
    if getattr(q, "env", None) is not None:
        q.env = None  # an opponent look-ahead team plays its plain ranking inside a trial (no trials in trials)
    return q


class _TryThenLibrary:
    """In a trial: start the candidate play at the first decision, then rank the library as usual."""

    def __init__(self, cand: Candidate, base: RankingPolicy) -> None:
        self.cand = cand
        self.base = base
        self.started = False
        self.last_decision = None

    def decide(self, obs: TeamView, reason: str) -> PlayInstance | None:
        if not self.started:
            self.started = True
            c = self.cand
            return PlayInstance(c.play, obs.team, c.side, c.assignment.binding, obs, c.score, c.components, "trial")
        return self.base.decide(obs, reason)

    def notify_end(self, inst: PlayInstance, t: float) -> None:
        self.base.notify_end(inst, t)


class LookaheadPolicy(RankingPolicy):
    def __init__(self, library: dict[str, Play], rng: np.random.Generator | None = None, top_k: int = 6,
                 rollouts: int = 4, horizon_s: float = 6.0, temperature: float = 0.01, name: str = "lookahead",
                 **kw) -> None:
        super().__init__(library, rng=rng, temperature=temperature, name=name, **kw)
        self.top_k = int(top_k)
        self.rollouts = int(rollouts)
        self.horizon_s = float(horizon_s)
        rc = load_config("training")["rewards"]
        self.w_goal, self.w_xg = float(rc["goal"]), float(rc.get("shot_xg", 0.0))
        self.env = None
        self.team = 0
        self.n_trials = 0

    def attach(self, env, team: int) -> None:
        self.env, self.team = env, team

    # -- trials ------------------------------------------------------------------------------

    def _trial(self, cand: Candidate, seed: int) -> float:
        env, team = self.env, self.team
        base = RankingPolicy(self.library, rng=np.random.default_rng(seed + 1), cfg=self.cfg,
                             temperature=self.temperature, name="library")
        base.cooldowns = dict(self.cooldowns)
        ours = _TryThenLibrary(cand, base)
        opp = fork_policy(env.loop.policies[1 - team], seed + 2)
        pols = (ours, opp) if team == 0 else (opp, ours)
        f = env.fork(*pols, seed=seed, horizon_s=self.horizon_s, drop_active=(team,))
        v0 = TeamView(f.state, team, f.ctx).epv()
        while f.step():
            pass
        v1 = TeamView(f.state, team, f.ctx).epv()
        value = v1 - v0
        for e in f.loop.result.events:
            if e["type"] == "goal":
                value += self.w_goal if e.get("team") == team else -self.w_goal
            elif e["type"] == "shot_taken":
                xg = float((e.get("data") or {}).get("xg") or 0.0)
                value += self.w_xg * xg if e.get("team") == team else -self.w_xg * xg
        self.n_trials += 1
        return float(value)

    def decide(self, obs: TeamView, reason: str) -> PlayInstance | None:
        if self.env is None or reason not in REAL_DECISIONS:
            return super().decide(obs, reason)
        cands = self.rank(obs, list(self.library.values()))
        feasible = sorted((c for c in cands if c.feasible), key=lambda c: -c.score)
        if len(feasible) <= 1:
            return super().decide(obs, reason)
        top = feasible[: self.top_k]
        seeds = [int(s) for s in self.rng.integers(1 << 31, size=self.rollouts)]  # shared by every candidate
        trials = {c.play.id: [self._trial(c, s) for s in seeds] for c in top}
        means = {pid: float(np.mean(v)) for pid, v in trials.items()}
        best = max(top, key=lambda c: means[c.play.id])
        record: dict[str, Any] = {
            "t": round(obs.t, 2), "team": obs.team, "reason": reason, "policy": self.name,
            "candidates": [c.record() for c in cands], "chosen": best.play.id, "chosen_source": best.play.source,
            "chosen_score": round(best.score, 5), "generator_used": False, "library_gap": False,
            "kept_active": False,
            "lookahead": {pid: {"mean": round(means[pid], 5), "sd": round(float(np.std(v)), 5),
                                "values": [round(x, 5) for x in v]} for pid, v in trials.items()},
        }
        record["decision_id"] = f"{obs.team}-la-{self.n_trials}"
        self.last_decision = record
        active = obs.active_plays.get(obs.team)
        if active is not None and not active.ended and active.play.id == best.play.id:
            record["kept_active"] = True
            return None
        return PlayInstance(best.play, obs.team, best.side, best.assignment.binding, obs, best.score,
                            best.components, record["decision_id"])
