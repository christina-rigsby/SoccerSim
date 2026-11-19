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


# -- who the player is (skill_aware, D-060) --------------------------------------------------


def _set(st, player, **caps):
    from soccersim.sim.state import CAP_INDEX

    for k, v in caps.items():
        st.caps[player, CAP_INDEX[k]] = v


def test_own_pass_chance_depends_on_the_passer_and_the_receiver():
    st, c = _state(carrier_at=(0.0, 0.0), opponents=[(1.5, 1.0)], teammate_at=(22.0, 6.0))
    r = [i for i in range(11) if st.kinds[i] != "GK"][6]
    _set(st, c, passing=0.95)
    good = TeamView(st, 0, CTX).pass_p_own(c, st.pos[r], "ground", r)
    _set(st, c, passing=0.2)
    poor = TeamView(st, 0, CTX).pass_p_own(c, st.pos[r], "ground", r)
    lane = TeamView(st, 0, CTX).pass_p(c, st.pos[r], "ground", r)
    assert good > poor and good <= lane + 1e-9
    _set(st, c, passing=0.95)
    _set(st, r, first_touch=0.1)
    assert TeamView(st, 0, CTX).pass_p_own(c, st.pos[r], "ground", r) < good


def test_duel_factor_follows_dribbling_against_tackling():
    from soccersim.executor.instincts import duel_factor

    st, c = _state(opponents=[(2.0, 0.0)])
    o = [o for o in range(11, 22) if st.kinds[o] != "GK"][0]
    _set(st, c, dribbling=0.9)
    _set(st, o, tackling=0.3)
    weak = duel_factor(TeamView(st, 0, CTX), c, o, protect=True)
    _set(st, c, dribbling=0.3)
    _set(st, o, tackling=0.9)
    strong = duel_factor(TeamView(st, 0, CTX), c, o, protect=True)
    assert weak < 1.0 < strong


def test_a_fast_carrier_carries_further():
    cfg = {**CARRIER, "skill_aware": True, "settle_s": 99.0}  # no passes: hold or carry
    dists = []
    for pace in (0.1, 0.9):
        st, c = _state(carrier_at=(10.0, 0.0))
        _set(st, c, pace=pace)
        d = carrier_instinct(TeamView(st, 0, CTX), cfg)
        assert d is not None
        dists.append(float(np.hypot(*(d.target - st.pos[c]))))
    assert dists[1] > dists[0]


def test_a_good_finisher_shoots_from_further_out():
    from soccersim.executor.shooting import shooting_config, shot_is_on

    cfg = {**shooting_config(), "enabled": True, "skill_aware": True, "min_xg": 0.1}
    st, c = _state(carrier_at=(33.0, 0.0))
    view = TeamView(st, 0, CTX)
    xg = view.xg_of(c)
    cfg["min_xg"] = xg * 1.1  # just out of range for a reference finisher
    _set(st, c, finishing=0.95)
    assert shot_is_on(TeamView(st, 0, CTX), cfg)
    _set(st, c, finishing=0.3)
    assert not shot_is_on(TeamView(st, 0, CTX), cfg)
