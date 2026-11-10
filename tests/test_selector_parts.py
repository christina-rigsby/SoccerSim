"""The learned selector's two switches: learned-only scoring and exploration."""

from __future__ import annotations

import numpy as np

from soccersim.dashboard.team_state import Context, TeamView
from soccersim.ranking import RankingPolicy, assign, score_play
from soccersim.ranking.selector import Candidate
from soccersim.schema import load_library
from soccersim.sim.env import MatchEnv
from soccersim.sim.scenarios import Scenario

LIB = load_library(promoted_runs=())
CTX = Context()


def _view():
    env = MatchEnv(randomise=False)
    env.reset(0, Scenario(type="mid_progression", attacking_team=0, randomise_capabilities=False))
    return TeamView(env.state, 0, CTX)


def test_learned_scoring_uses_only_the_value_model():
    v = _view()
    pol = RankingPolicy(LIB)
    play = LIB["recycle_possession"]
    asg = assign(play, v, v.side_from_ball(), pol.cfg)
    cfg = {**pol.cfg, "critic": {"enabled": True, "weight": 1.0, "replace_prior": True}}
    score, comp = score_play(play, v, asg, cfg, critic=lambda view, p, b: 0.0123)
    assert score == 0.0123 and comp["critic"] == 0.0123 and "graph" in comp
    cfg["critic"]["replace_prior"] = False
    mixed, _ = score_play(play, v, asg, cfg, critic=lambda view, p, b: 0.0123)
    assert mixed != score


def test_exploration_sometimes_calls_a_play_that_is_not_the_best():
    plays = [LIB[k] for k in ("recycle_possession", "switch_of_play", "third_man_combination")]
    cands = [Candidate(p, True, score=s) for p, s in zip(plays, (0.03, 0.01, 0.0), strict=True)]
    greedy = RankingPolicy(LIB, rng=np.random.default_rng(0))
    assert {greedy._select(cands).play.id for _ in range(50)} == {"recycle_possession"}
    explore = RankingPolicy(LIB, rng=np.random.default_rng(0))
    explore.epsilon = 0.5
    picks = [explore._select(cands).play.id for _ in range(400)]
    share = picks.count("recycle_possession") / len(picks)
    assert 0.55 < share < 0.80  # 0.5 greedy + 0.5 * 1/3 random
