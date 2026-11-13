"""Player instincts: the ball carrier outside a play acts by value; off-ball players seek space."""

from __future__ import annotations

import numpy as np

from soccersim.controllers.shape import shape_targets
from soccersim.dashboard.team_state import Context, TeamView
from soccersim.executor.instincts import carrier_instinct, instincts_config, off_ball_targets
from soccersim.sim.env import MatchEnv
from soccersim.sim.scenarios import Scenario

CTX = Context()
CARRIER = {**instincts_config()["carrier"], "enabled": True}
OFF_BALL = {**instincts_config()["off_ball"], "enabled": True}


def _state(carrier_at=(0.0, 0.0), opponents=None, teammate_at=None):
    """Team 0 has the ball at ``carrier_at``; opponents far away unless placed."""
    env = MatchEnv(randomise=False)
    env.reset(0, Scenario(type="mid_progression", attacking_team=0, randomise_capabilities=False))
    st = env.state
    outfield = [i for i in range(11) if st.kinds[i] != "GK"]
    c = outfield[5]
    st.pos[c] = np.asarray(carrier_at, float)
    st.ball.pos = st.pos[c].copy()
    st.ball.owner, st.ball.owner_since, st.possession, st.restart = c, st.t - 1.0, 0, None
    for k, o in enumerate(o for o in range(11, 22) if st.kinds[o] != "GK"):
        st.pos[o] = np.array([-45.0, -30.0 + 6 * k])
    for k, p in enumerate(opponents or []):
        o = [o for o in range(11, 22) if st.kinds[o] != "GK"][k]
        st.pos[o] = np.asarray(p, float)
    if teammate_at is not None:
        st.pos[outfield[6]] = np.asarray(teammate_at, float)
    return st, c


def test_disabled_instinct_leaves_the_default():
    st, _ = _state()
    assert carrier_instinct(TeamView(st, 0, CTX), {**CARRIER, "enabled": False}) is None


def test_carrier_with_space_ahead_moves_forward():
    st, c = _state(carrier_at=(10.0, 0.0))
    d = carrier_instinct(TeamView(st, 0, CTX), CARRIER)
    assert d is not None and d.label in ("instinct_carry", "instinct_pass")
    if d.label == "instinct_carry":
        assert d.target[0] > st.pos[c][0]  # forward, in our attacking frame (team 0 attacks +x)


def test_pressed_carrier_does_not_just_stand_there():
    # An opponent 1 m away and a free teammate ahead: holding still is the worst option.
    st, c = _state(carrier_at=(0.0, 0.0), opponents=[(1.0, 0.0)], teammate_at=(12.0, 8.0))
    d = carrier_instinct(TeamView(st, 0, CTX), CARRIER)
    assert d is not None and d.label in ("instinct_carry", "instinct_pass")


def test_off_ball_targets_are_onside_spaced_and_near_the_shape():
    st, c = _state(carrier_at=(5.0, 0.0))
    v = TeamView(st, 0, CTX)
    shape_arr = shape_targets(st, 0, True, v.ball, CTX.formations["shape"])
    shape = {int(p): shape_arr[k] for k, p in enumerate(v.us)}
    t = off_ball_targets(v, shape, set(), OFF_BALL)
    assert t, "someone should look for space"
    assert c not in t and st.gk(0) not in t
    deepest = sorted((int(p) for p in v.outfield(v.us)), key=lambda p: shape[p][0])[: OFF_BALL["rest_defence"]]
    assert not set(deepest) & set(t), "rest defence keeps its shape"
    for p, pt in t.items():
        assert np.hypot(*(pt - shape[p])) <= OFF_BALL["radius_m"] + 1e-6
        assert pt[0] <= max(v.offside_x, shape[p][0]) + 1e-6
    # Crowding is penalised, so players spread out: no two chosen spots on top of each other.
    pts = np.array(list(t.values()))
    d = np.linalg.norm(pts[:, None] - pts[None, :], axis=2) + np.eye(len(pts)) * 99
    assert d.min() > 2.0


def test_no_space_seeking_without_the_ball():
    st, _ = _state()
    st.possession = 1
    v = TeamView(st, 0, CTX)
    shape_arr = shape_targets(st, 0, False, v.ball, CTX.formations["shape"])
    assert off_ball_targets(v, {int(p): shape_arr[k] for k, p in enumerate(v.us)}, set(), OFF_BALL) == {}
