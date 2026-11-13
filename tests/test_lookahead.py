"""Forking a game and the look-ahead team."""

from __future__ import annotations

import numpy as np

from soccersim.ranking.lookahead import LookaheadPolicy
from soccersim.ranking.selector import RankingPolicy
from soccersim.schema import load_library
from soccersim.sim.env import MatchEnv
from soccersim.sim.scenarios import Scenario

LIB = load_library(promoted_runs=())


def _env(seed: int = 3) -> MatchEnv:
    env = MatchEnv(randomise=False, record_frames=False)
    env.reset(seed, Scenario(type="mid_progression", attacking_team=0, randomise_capabilities=False))
    return env


def test_a_fork_plays_on_without_touching_the_original():
    env = _env()
    env.begin(RankingPolicy(LIB, rng=np.random.default_rng(0)), RankingPolicy(LIB, rng=np.random.default_rng(1)))
    for _ in range(30):
        env.step()
    pos, t, n_ev = env.state.pos.copy(), env.state.t, len(env.state.events)
    f = env.fork(RankingPolicy(LIB, rng=np.random.default_rng(2)), RankingPolicy(LIB, rng=np.random.default_rng(3)),
                 seed=7, horizon_s=3.0)
    while f.step():
        pass
    assert f.state.t >= t + 3.0 - 1e-6
    assert not np.allclose(f.state.pos, pos)
    assert env.state.t == t and np.allclose(env.state.pos, pos) and len(env.state.events) == n_ev
    # The original carries on as if nothing happened.
    assert env.step()


def test_run_is_unchanged_by_the_begin_step_finish_split():
    a = _env(5).run(RankingPolicy(LIB, rng=np.random.default_rng(0)), RankingPolicy(LIB, rng=np.random.default_rng(1)),
                    max_time_s=15)
    env = _env(5)
    env.begin(RankingPolicy(LIB, rng=np.random.default_rng(0)), RankingPolicy(LIB, rng=np.random.default_rng(1)),
              max_time_s=15)
    while env.step():
        pass
    b = env.finish()
    assert a.duration_s == b.duration_s and a.end_cause == b.end_cause
    assert [e["type"] for e in a.events] == [e["type"] for e in b.events]


def test_the_lookahead_team_tries_each_candidate_with_the_same_seeds():
    env = _env()
    la = LookaheadPolicy(LIB, rng=np.random.default_rng(0), top_k=2, rollouts=2, horizon_s=1.0, screen=0)
    res = env.run(la, RankingPolicy(LIB, rng=np.random.default_rng(1)), max_time_s=4, stop_on_goal=False,
                  stop_on_turnover=False)
    decs = [d for d in res.decisions if d.get("lookahead")]
    assert decs, "at least one decision should have been made by trying plays"
    d = decs[0]
    assert 1 <= len(d["lookahead"]) <= 2
    assert all(len(v["values"]) == 2 for v in d["lookahead"].values())
    best = max(d["lookahead"], key=lambda p: d["lookahead"][p]["mean"])
    assert d["chosen"] == best
    assert la.n_trials >= 2


def test_screening_gives_the_finalists_the_full_number_of_trials():
    env = _env()
    la = LookaheadPolicy(LIB, rng=np.random.default_rng(0), top_k=4, rollouts=3, horizon_s=1.0, screen=1,
                         finalists=2)
    res = env.run(la, RankingPolicy(LIB, rng=np.random.default_rng(1)), max_time_s=4, stop_on_goal=False,
                  stop_on_turnover=False)
    d = next(d for d in res.decisions if d.get("lookahead"))
    counts = sorted(len(v["values"]) for v in d["lookahead"].values())
    assert counts[-1] == 3 or len(counts) <= 2
    assert d["lookahead"][d["chosen"]]["values"] and len(d["lookahead"][d["chosen"]]["values"]) == max(counts)


def _spy_calls(opponent_model: str) -> tuple[int, int]:
    """(calls to the real opponent's decide, decisions it made in the real game)."""
    calls = []

    class Spy(RankingPolicy):
        def decide(self, obs, reason):
            calls.append(1)
            return super().decide(obs, reason)

    env = _env()
    la = LookaheadPolicy(LIB, rng=np.random.default_rng(0), top_k=3, rollouts=2, horizon_s=1.0, screen=0,
                         opponent_model=opponent_model, record_state=True)
    res = env.run(la, Spy(LIB, rng=np.random.default_rng(1)), max_time_s=4, stop_on_goal=False,
                  stop_on_turnover=False)
    d = next(d for d in res.decisions if d.get("lookahead"))
    assert "state" in d and set(d["sides"]) == set(d["lookahead"])
    return len(calls), sum(1 for x in res.decisions if x["team"] == 1)


def test_the_fair_lookahead_never_consults_the_real_opponent():
    calls, real = _spy_calls("library")
    assert calls == real  # every call came from the real game, none from the trials
    calls, real = _spy_calls("copy")
    assert calls > real  # the upper-bound version does ask (copies of) the real opponent
