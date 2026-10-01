"""M3: Module 1 geometry and the predicate evaluator (spec §3, §4.5, §8)."""

from __future__ import annotations

import numpy as np
import pytest

from soccersim.config import load_config
from soccersim.dashboard.evaluator import Evaluator
from soccersim.dashboard.lines import kmeans_1d
from soccersim.dashboard.pitch_control import pitch_control
from soccersim.dashboard.team_state import Context, TeamView
from soccersim.dashboard.xt import fit_xt, placeholder_xt
from soccersim.dashboard.zones import GRID_NX, GRID_NY, GRID_POINTS, zone_mask
from soccersim.sim.ball import emit, gain_control
from soccersim.sim.scenarios import Scenario, build_state

CTX = Context()


def make_state(home=None, away=None, ball=(0.0, 0.0), owner=-1):
    """A neutral state: both teams at their formation bases unless positions are given."""
    cfg = load_config("sim")
    st = build_state(np.random.default_rng(0), Scenario(randomise_capabilities=False), cfg)
    if home is not None:
        st.pos[:11] = np.asarray(home, float)
    if away is not None:
        st.pos[11:] = np.asarray(away, float)
    st.ball.pos = np.asarray(ball, float)
    if owner >= 0:
        st.pos[owner] = st.ball.pos
        st.last_control_team = None
        gain_control(st, owner, cfg)
    return st


def ev_for(st, team=0, binding=None, side=None, **kw):
    v = TeamView(st, team, CTX)
    return Evaluator(v, binding or {}, side if side is not None else v.side_from_ball(), **kw)


# -- geometry ---------------------------------------------------------------------------------


def test_grid_is_53_by_34():
    assert (GRID_NX, GRID_NY) == (53, 34) and len(GRID_POINTS) == 53 * 34


def test_pitch_control_symmetric_setup_is_half():
    us = np.array([[-10.0, 5.0], [-20.0, -8.0]])
    them = -us
    pts = np.array([[0.0, 0.0], [0.0, 3.0], [0.0, -12.0]])
    pc = pitch_control(pts * [0, 1], us, np.zeros_like(us), np.full(2, 8.0), them, np.zeros_like(them),
                       np.full(2, 8.0))
    assert pc[0] == pytest.approx(0.5)
    # Mirror pairs: control(p) for us == control(-p) for them.
    a = pitch_control(pts, us, np.zeros_like(us), np.full(2, 8.0), them, np.zeros_like(them), np.full(2, 8.0))
    b = pitch_control(-pts, them, np.zeros_like(them), np.full(2, 8.0), us, np.zeros_like(us), np.full(2, 8.0))
    assert np.allclose(a, b)


def test_pitch_control_favours_the_nearer_team():
    us, them = np.array([[0.0, 0.0]]), np.array([[20.0, 0.0]])
    pc = pitch_control(np.array([[2.0, 0.0], [18.0, 0.0]]), us, np.zeros((1, 2)), np.full(1, 8.0), them,
                       np.zeros((1, 2)), np.full(1, 8.0))
    assert pc[0] > 0.9 and pc[1] < 0.1


def test_pitch_control_is_momentum_aware():
    us, them = np.array([[0.0, 0.0]]), np.array([[10.0, 0.0]])
    pt = np.array([[5.0, 0.0]])
    still = pitch_control(pt, us, np.zeros((1, 2)), np.full(1, 8.0), them, np.zeros((1, 2)), np.full(1, 8.0))
    away = pitch_control(pt, us, np.zeros((1, 2)), np.full(1, 8.0), them, np.array([[8.0, 0.0]]), np.full(1, 8.0))
    assert away[0] > still[0]


def test_zones_and_side_mirroring():
    p = np.array([[30.0, 25.0]])
    assert zone_mask(p, "final_third.near_wing", 1.0)[0]
    assert zone_mask(p, "final_third.far_wing", -1.0)[0]
    assert zone_mask(p, "*.near_wing", 1.0)[0] and zone_mask(p, "final_third.*", 1.0)[0]
    assert zone_mask(np.array([[40.0, 5.0]]), "box", 1.0)[0]
    assert zone_mask(np.array([[25.0, 2.0]]), "zone14", -1.0)[0]
    assert zone_mask(np.array([[44.0, 3.0]]), "cutback_zone", 1.0)[0]
    assert zone_mask(np.array([[50.0, 4.0]]), "near_post_area", 1.0)[0]
    assert not zone_mask(np.array([[50.0, 4.0]]), "near_post_area", -1.0)[0]
    assert zone_mask(np.array([[50.0, 4.0]]), "far_post_area", -1.0)[0]
    assert zone_mask(np.array([[-33.0, 0.0]]), "own_box_edge", 1.0)[0]
    # Every grid cell is in exactly one band.lane zone.
    from soccersim.schema.vocab import BANDS, LANES
    total = sum(zone_mask(GRID_POINTS, f"{b}.{lane}", 1.0).astype(int) for b in BANDS for lane in LANES)
    assert np.all(total == 1)


def test_kmeans_lines_and_collapse():
    c = kmeans_1d(np.array([-30, -31, -29, -10, -11, -9, 10, 11, 9, 12]))
    assert len(c) == 3 and c[0] == pytest.approx(-30, abs=1) and c[2] == pytest.approx(10.5, abs=1)
    assert len(kmeans_1d(np.array([1.0, 1.2, 0.9, 1.1]))) == 1


def test_lines_and_heights():
    st = make_state()
    v = TeamView(st, 0, CTX)
    lines = v.lines
    assert lines["opp_first_line"] < lines["opp_second_line"] < lines["opp_last_line"]
    assert lines["our_last_line"] < lines["our_second_line"] < lines["our_first_line"]
    assert v.line_height("opp_last_line") == pytest.approx(52.5 - lines["opp_last_line"])
    assert v.line_height("our_last_line") == pytest.approx(lines["our_last_line"] + 52.5)


def test_xt_placeholder_shape_and_value_iteration():
    xt = placeholder_xt()
    assert xt.values.shape == (12, 16)
    assert xt.value(np.array([45.0, 0.0])) > xt.value(np.array([0.0, 0.0])) > 0
    assert xt.value(np.array([45.0, 0.0])) > xt.value(np.array([45.0, 30.0]))
    # A fitted surface: shots from near goal score; moves flow toward goal.
    rng = np.random.default_rng(0)
    starts = rng.uniform([-50, -30], [30, 30], size=(3000, 2))
    ends = starts + np.array([12.0, 0.0])
    moves = np.hstack([starts, ends])
    shots = rng.uniform([38, -10], [50, 10], size=(300, 2))
    goals = rng.random(300) < 0.3
    fitted = fit_xt(moves, rng.random(3000) < 0.7, shots, goals, prior=xt)
    assert fitted.value(np.array([44.0, 0.0])) > fitted.value(np.array([-30.0, 0.0]))


def test_epv_sign_follows_possession():
    st = make_state(ball=(30.0, 0.0), owner=9)
    assert TeamView(st, 0, CTX).epv() > 0 > TeamView(st, 1, CTX).epv()


# -- predicates -------------------------------------------------------------------------------------


def test_possession_and_has_ball():
    st = make_state(ball=(0.0, 5.0), owner=6)
    e = ev_for(st, binding={"R1": [6], "R2": [7]})
    assert e.pred({"possession": "us"}) and not e.pred({"possession": "them"})
    assert e.pred({"has_ball": "R1"}) and not e.pred({"has_ball": "R2"})
    assert e.pred({"has_ball": "teammate"}) and not e.pred({"has_ball": "opponent"})
    assert ev_for(st, team=1).pred({"possession": "them"})


def test_combinators_and_always():
    st = make_state(ball=(0.0, 5.0), owner=6)
    e = ev_for(st)
    assert e.pred("always")
    assert e.pred({"all": [{"possession": "us"}, {"not": {"possession": "them"}}]})
    assert e.pred({"any": [{"possession": "them"}, "always"]})
    assert e.pred({"all": []}) and not e.pred({"any": []})


def test_ball_in_zone_and_role_in_zone():
    st = make_state(ball=(30.0, 25.0), owner=8)
    e = ev_for(st, binding={"R1": [8]})
    assert e.side == 1.0
    assert e.pred({"ball_in_zone": "final_third.near_wing"})
    assert e.pred({"ball_in_zone": ["box", "final_third.*"]})
    assert e.pred({"role_in_zone": {"role": "R1", "zone": "*.near_wing"}})


def test_dist_and_ahead_of():
    st = make_state(ball=(0.0, 0.0), owner=6)
    st.pos[7] = [10.0, 0.0]
    e = ev_for(st, binding={"R1": [6], "R2": [7]})
    assert e.pred({"dist": {"a": "role:R1", "b": "role:R2", "lt": 10.5, "gt": 9.5}})
    assert e.pred({"ahead_of": {"a": "role:R2", "b": "role:R1", "by": 9}})
    assert not e.pred({"ahead_of": {"a": "role:R1", "b": "role:R2", "by": 0}})
    assert e.pred({"dist": {"a": "ball", "b": "anchor:goal", "eq": 52.5}})


def test_pressure_on():
    st = make_state(ball=(0.0, 0.0), owner=6)
    st.pos[15] = [1.0, 0.0]
    e = ev_for(st, binding={"R1": [6]})
    assert e.pred({"pressure_on": {"ref": "role:R1", "lt": 1.5}})
    assert e.pred({"pressure_on": {"ref": "ball_holder", "lt": 1.5}})
    st.pos[11:] = np.column_stack([np.full(11, 40.0), np.linspace(-30, 30, 11)])
    assert ev_for(st, binding={"R1": [6]}).pred({"pressure_on": {"ref": "role:R1", "gt": 3}})


def test_lane_open():
    st = make_state(ball=(0.0, 0.0), owner=6)
    st.pos[7] = [15.0, 0.0]
    st.pos[11:] = np.column_stack([np.linspace(30, 50, 11), np.linspace(-30, 30, 11)])
    e = ev_for(st, binding={"R1": [6], "R2": [7]})
    assert e.pred({"lane_open": {"from": "R1", "to": {"role": "R2"}, "min_p": 0.8}})
    st.pos[11] = [7.5, 0.3]
    e = ev_for(st, binding={"R1": [6], "R2": [7]})
    assert not e.pred({"lane_open": {"from": "ball_holder", "to": {"role": "R2"}, "min_p": 0.6}})


def test_pc_at_xg_line_height():
    st = make_state(ball=(44.0, 0.0), owner=9)
    e = ev_for(st)
    assert e.pred({"xg": {"ref": "ball_holder", "gt": 0.05}})
    assert e.pred({"pc_at": {"target": {"anchor": "own_goal", "offset": [3, 0]}, "gt": 0.6}})
    assert e.pred({"line_height": {"line": "opp_last_line", "gt": 0}})


def test_count_goal_side_teammates_near():
    st = make_state(ball=(0.0, 0.0), owner=6)
    e = ev_for(st)
    n_them_ahead = int(np.sum(st.pos[12:, 0] > 0.0))
    assert e.pred({"goal_side_count": {"team": "them", "eq": n_them_ahead}})
    assert e.pred({"count_in_zone": {"team": "us", "zone": "*.*", "eq": 11}})
    near = int(np.sum(np.linalg.norm(st.pos[:11] - st.ball.pos, axis=1) <= 15) - 1)
    assert e.pred({"teammates_near": {"ref": "ball_holder", "radius": 15, "eq": near}})


def test_onside():
    st = make_state(ball=(0.0, 0.0), owner=6)
    st.pos[11:] = np.column_stack([np.full(11, 20.0), np.linspace(-30, 30, 11)])
    st.pos[11] = [50.0, 0.0]
    st.pos[9] = [25.0, 0.0]
    assert not ev_for(st, binding={"R2": [9]}).pred({"onside": "R2"})
    st.pos[9] = [18.0, 0.0]
    assert ev_for(st, binding={"R2": [9]}).pred({"onside": "R2"})


def test_events_and_windows():
    st = make_state(ball=(0.0, 0.0), owner=6)
    st.tick, st.t = 50, 5.0
    emit(st, "pass_completed", 0)
    st.tick, st.t = 60, 6.0
    e = ev_for(st, event_default_tick=45)
    assert e.pred({"event": "pass_completed"})
    assert not ev_for(st, event_default_tick=55).pred({"event": "pass_completed"})
    assert e.pred({"event": {"type": "pass_completed", "within_s": 1.5}})
    assert not e.pred({"event": {"type": "pass_completed", "within_s": 0.5}})
    assert not ev_for(st, team=1, event_default_tick=0).pred({"event": "pass_completed"})


def test_ball_lines_elapsed_game():
    st = make_state(ball=(45.0, 0.0), owner=9)
    st.t = 7.0
    e = ev_for(st, play_start_t=1.0, step_start_t=5.0)
    assert e.pred({"ball_beyond_line": {"line": "opp_first_line"}})
    assert not e.pred({"ball_behind_line": {"line": "opp_first_line"}})
    assert e.pred({"elapsed_s": {"gt": 5.5}}) and e.pred({"step_elapsed_s": {"lt": 2.5}})
    st.score = [0, 1]
    st.minute0 = 85
    assert ev_for(st).pred({"game": {"score_diff": {"lt": 0}, "minute": {"gt": 80}}})


def test_targets_resolve():
    st = make_state(ball=(10.0, 20.0), owner=8)
    st.vel[7] = [5.0, 0.0]
    e = ev_for(st, binding={"R1": [8], "R2": [7]})
    pt, who = e.target({"role": "R2", "lead": 4})
    assert who == 7 and np.allclose(pt, st.pos[7] + [4.0, 0.0])
    pt, _ = e.target({"anchor": "ball", "offset": [3, 5]})
    assert np.allclose(pt, [13.0, 25.0])                        # side = +1
    pt, _ = e.target({"zone": "box", "pick": "centroid"})
    assert pt[0] > 36
    pt, _ = e.target({"space_behind": {"line": "opp_last_line", "lane": "center", "depth": 6}})
    assert pt[0] == pytest.approx(min(e.v.line_x("opp_last_line") + 6, 50.5)) and pt[1] == 0.0
    pt, who = e.target({"best_teammate": {"score": "pass_p"}})
    assert who >= 0 and who != 8
    pt, who = e.target({"opponent": "ball_carrier"})
    assert who >= 11
    pt, _ = e.target({"pc_best": {"anchor": "ball", "radius": 8}, "score": "pc"})
    assert np.hypot(*(pt - st.ball.pos)) <= 9.5


def test_selectors():
    st = make_state(ball=(-10.0, 0.0), owner=15)
    e = ev_for(st, binding={"R1": [6]})
    assert e.selector("ball_carrier") == 15
    assert e.selector("nearest_to_ball") == 15
    r1, r2 = e.selector("nearest_receiver"), e.selector("second_receiver")
    assert r1 >= 11 and r2 >= 11 and r1 != r2 != 15
    assert e.selector("most_dangerous") >= 11
    assert e.selector("nearest_to_role:R1") >= 11
