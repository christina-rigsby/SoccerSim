"""Shoot when on: a good, clear chance is taken; a blocked or poor one is not."""

from __future__ import annotations

import numpy as np

from soccersim.dashboard.evaluator import Evaluator
from soccersim.dashboard.team_state import Context, TeamView
from soccersim.executor.runner import team_directives
from soccersim.executor.shooting import shot_blockers, shot_is_on
from soccersim.sim.env import MatchEnv
from soccersim.sim.scenarios import Scenario

CTX = Context()
CFG = {"enabled": True, "min_xg": 0.10, "block_range_m": 10.0, "cone_margin_m": 0.5, "settle_s": 0.2}


def _chance(shooter_x: float, defender_at=None):
    """Our player with the ball at (shooter_x, 0), team 0 attacking +x; every outfield opponent far away
    unless one is placed at ``defender_at``."""
    env = MatchEnv(randomise=False)
    env.reset(0, Scenario(type="final_third_attack", attacking_team=0, randomise_capabilities=False))
    st = env.state
    striker = next(i for i in range(11) if st.kinds[i] != "GK")
    st.pos[striker] = np.array([shooter_x, 0.0])
    st.ball.pos = st.pos[striker].copy()
    st.ball.owner = striker
    st.ball.owner_since = st.t - 1.0
    for k, o in enumerate(range(11, 22)):
        if st.kinds[o] == "GK":
            continue
        st.pos[o] = np.array([-40.0, -30.0 + 4 * k])
    if defender_at is not None:
        o = next(o for o in range(11, 22) if st.kinds[o] != "GK")
        st.pos[o] = np.asarray(defender_at, float)
    st.possession = 0
    return st, TeamView(st, 0, CTX), striker


def test_a_clear_good_chance_is_taken():
    st, v, s = _chance(38.0)
    assert v.xg_of(s) >= 0.10 and not shot_blockers(v, s, 10.0, 0.5)
    assert shot_is_on(v, CFG)


def test_a_defender_in_the_way_stops_the_shot():
    st, v, s = _chance(38.0, defender_at=(43.0, 0.5))
    assert shot_blockers(v, s, 10.0, 0.5)
    assert not shot_is_on(v, CFG)
    ev = Evaluator(v, {"R1": [s]}, 1.0)
    assert not ev.pred({"shot_clear": {"ref": "role:R1"}})


def test_a_defender_beside_the_cone_does_not_block():
    st, v, s = _chance(38.0, defender_at=(43.0, 8.0))
    assert not shot_blockers(v, s, 10.0, 0.5)
    ev = Evaluator(v, {"R1": [s]}, 1.0)
    assert ev.pred({"shot_clear": {"ref": "role:R1"}})


def test_no_shot_from_distance_or_when_disabled():
    st, v, s = _chance(10.0)
    assert not shot_is_on(v, CFG)
    st, v, s = _chance(38.0)
    assert not shot_is_on(v, {**CFG, "enabled": False})


def test_the_rule_issues_a_shot_directive():
    st, v, s = _chance(38.0)
    out = team_directives(v, None)
    assert out[s].ball is not None and out[s].ball.kind == "shoot"
