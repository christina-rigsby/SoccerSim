"""M1: simulator core — one test group per model, determinism, speed (spec §7.2, §14)."""

from __future__ import annotations

import time

import numpy as np
import pytest

from soccersim.config import load_config
from soccersim.ranking import RankingPolicy
from soccersim.schema import load_library
from soccersim.sim import shots
from soccersim.sim.ball import BallCommand, gain_control, offside_players, release, step_ball
from soccersim.sim.duels import control_prob, tackle_success_prob
from soccersim.sim.env import MatchEnv
from soccersim.sim.passmodel import assess_pass, noisy_target, plan_pass
from soccersim.sim.physics import max_accel, max_speed, step_players
from soccersim.sim.scenarios import Scenario, build_state, setup_scenario
from soccersim.sim.state import CAP_INDEX


@pytest.fixture(scope="module")
def cfg():
    return load_config("sim")


def fresh(cfg, seed=0, typ="mid_progression"):
    rng = np.random.default_rng(seed)
    sc = Scenario(type=typ, randomise_capabilities=False)
    st = build_state(rng, sc, cfg)
    setup_scenario(st, sc, rng, cfg)
    return st, rng


# -- movement ---------------------------------------------------------------------------


def test_speed_formula_and_stamina_scaling(cfg):
    st, _ = fresh(cfg)
    pace = st.caps[:, CAP_INDEX["pace"]]
    assert np.allclose(max_speed(st, cfg), 7.0 + 2.5 * pace)
    st.stamina[:] = 0.0
    assert np.allclose(max_speed(st, cfg), (7.0 + 2.5 * pace) * 0.85)
    acc = st.caps[:, CAP_INDEX["acceleration"]]
    assert np.allclose(max_accel(st, cfg), 3.0 + 2.0 * acc)


def test_players_respect_accel_and_top_speed(cfg):
    st, _ = fresh(cfg)
    st.ball.owner = -1
    st.vel[:] = 0
    targets = st.pos + np.array([60.0, 0.0])
    vmax = max_speed(st, cfg)
    amax = max_accel(st, cfg)
    step_players(st, targets, np.ones(22), cfg, 0.1)
    assert np.all(np.linalg.norm(st.vel, axis=1) <= amax * 0.1 + 1e-6)
    for _ in range(80):
        step_players(st, st.pos + np.array([60.0, 0.0]), np.ones(22), cfg, 0.1)
    assert np.all(np.linalg.norm(st.vel, axis=1) <= vmax + 1e-6)


def test_sprinting_drains_stamina(cfg):
    st, _ = fresh(cfg)
    st.ball.owner = -1
    for _ in range(50):
        step_players(st, st.pos + np.array([60.0, 0.0]), np.ones(22), cfg, 0.1)
    assert np.all(st.stamina < 1.0)


# -- ball / pass model ------------------------------------------------------------------------


def test_ground_pass_decelerates_and_arrives(cfg):
    plan = plan_pass(np.zeros(2), np.array([20.0, 0.0]), "ground", cfg)
    assert not plan.air
    # v_end^2 = v0^2 - 2 f d
    v_end = np.sqrt(plan.v0**2 - 2 * cfg["ball"]["friction"] * 20.0)
    assert v_end == pytest.approx(cfg["pass"]["arrival_speed"]["ground"], rel=1e-6)
    assert np.all(np.diff(plan.times) > 0)


def test_lofted_pass_is_aerial_and_uncontested_in_flight(cfg):
    origin, target = np.zeros(2), np.array([30.0, 0.0])
    # A defender standing on the midpoint of the path does not intercept an aerial ball.
    a = assess_pass(origin, target, "lofted", np.array([[15.0, 0.0]]), np.zeros((1, 2)), np.array([8.0]), cfg)
    g = assess_pass(origin, target, "ground", np.array([[15.0, 0.0]]), np.zeros((1, 2)), np.array([8.0]), cfg)
    assert a.plan.air and a.p_intercept[0] < 0.2
    assert g.p_intercept[0] > 0.85


def test_lane_probability_drops_with_defender_in_lane(cfg):
    origin, target = np.zeros(2), np.array([20.0, 0.0])
    far = assess_pass(origin, target, "ground", np.array([[10.0, 15.0]]), np.zeros((1, 2)), np.array([8.0]), cfg)
    near = assess_pass(origin, target, "ground", np.array([[10.0, 1.0]]), np.zeros((1, 2)), np.array([8.0]), cfg)
    assert far.p_success > 0.9 > near.p_success


def test_execution_samples_the_same_intercept_model(cfg):
    """Empirical interception rate of released passes matches the model's probability."""
    st, rng = fresh(cfg)
    opp = list(range(11, 22))
    base_pos = st.pos.copy()
    passer = st.ball.owner
    target = st.pos[passer] + np.array([18.0, 4.0])
    intercepted = 0
    n = 400
    cfg2 = {**cfg, "pass": {**cfg["pass"], "noise": {**cfg["pass"]["noise"], "angle_base_deg": 0.0,
                                                    "speed_base": 0.0}}}
    vmax = max_speed(st, cfg2)
    expect = 1 - np.prod(1 - assess_pass(st.pos[passer], target, "ground", st.pos[opp], st.vel[opp], vmax[opp],
                                         cfg2).p_intercept)
    for _ in range(n):
        st.pos = base_pos.copy()
        st.ball.owner = passer
        release(st, BallCommand("pass", target, "ground", -1), cfg2, rng)
        intercepted += st.ball.flight.intercept_player >= 0
    assert intercepted / n == pytest.approx(expect, abs=0.07)


def test_pass_noise_scales_with_skill(cfg):
    rng = np.random.default_rng(1)
    o, t = np.zeros(2), np.array([25.0, 0.0])
    good = [np.hypot(*(noisy_target(rng, o, t, "ground", 0.95, 0.0, cfg) - t)) for _ in range(300)]
    bad = [np.hypot(*(noisy_target(rng, o, t, "ground", 0.2, 0.0, cfg) - t)) for _ in range(300)]
    assert np.mean(bad) > 3 * np.mean(good)


# -- control, duels -----------------------------------------------------------------------------


def test_control_probability_monotone(cfg):
    st, _ = fresh(cfg)
    p = 5
    assert control_prob(st, p, 5.0, 10.0, cfg) > control_prob(st, p, 20.0, 10.0, cfg)
    assert control_prob(st, p, 5.0, 10.0, cfg) > control_prob(st, p, 5.0, 0.5, cfg)


def test_tackle_probability_depends_on_skills(cfg):
    st, _ = fresh(cfg)
    d, c = 12, 5
    st.caps[d, CAP_INDEX["tackling"]] = 0.9
    st.caps[c, CAP_INDEX["dribbling"]] = 0.3
    hi = tackle_success_prob(st, d, c, cfg, False, "press")
    st.caps[d, CAP_INDEX["tackling"]] = 0.3
    st.caps[c, CAP_INDEX["dribbling"]] = 0.9
    lo = tackle_success_prob(st, d, c, cfg, False, "press")
    assert hi > lo


# -- shots ------------------------------------------------------------------------------------


def test_xg_shape(cfg):
    assert shots.xg(np.array([47.0, 0.0]), cfg=cfg) > shots.xg(np.array([35.0, 0.0]), cfg=cfg)
    assert shots.xg(np.array([42.0, 0.0]), cfg=cfg) > shots.xg(np.array([42.0, 18.0]), cfg=cfg)
    assert shots.xg(np.array([41.5, 0.0]), cfg=cfg) == pytest.approx(0.27, abs=0.05)  # penalty spot, open play
    assert shots.xg(np.array([10.0, 0.0]), cfg=cfg) == 0.0
    assert shots.xg(np.array([47.0, 0.0]), 1.0, cfg=cfg) < shots.xg(np.array([47.0, 0.0]), 0.0, cfg=cfg)


def test_goalkeeper_position_matters(cfg):
    shooter = np.array([40.0, 0.0])
    good = shots.gk_factor(shooter, np.array([49.5, 0.0]), cfg)
    bad = shots.gk_factor(shooter, np.array([50.0, 6.0]), cfg)
    assert good < bad


# -- restarts, offside, events -------------------------------------------------------------------


def test_ball_out_over_touchline_gives_throw_in(cfg):
    st, rng = fresh(cfg)
    st.ball.owner = -1
    st.ball.flight = None
    st.ball.pos = np.array([0.0, 33.9])
    st.ball.vel = np.array([0.0, 5.0])
    st.ball.last_touch_team = 0
    step_ball(st, cfg, rng, 0.1)
    assert st.restart is not None and st.restart.type == "throw_in" and st.restart.team == 1
    assert any(e.type == "ball_out" for e in st.events.events)


def test_ball_over_goal_line_corner_or_goal_kick(cfg):
    for last, expect in ((1, ("corner", 0)), (0, ("goal_kick", 1))):
        st, rng = fresh(cfg)
        st.ball.owner = -1
        st.ball.flight = None
        st.ball.pos = np.array([52.4, 10.0])
        st.ball.vel = np.array([5.0, 0.0])
        st.ball.last_touch_team = last
        step_ball(st, cfg, rng, 0.1)
        assert (st.restart.type, st.restart.team) == expect


def test_offside_judged_at_release(cfg):
    st, _ = fresh(cfg)
    st.ball.owner = 5
    st.ball.pos = np.array([0.0, 0.0])
    st.pos[5] = st.ball.pos
    st.pos[9] = np.array([45.0, 0.0])            # far beyond the defence
    for i in range(11, 22):
        st.pos[i] = np.array([30.0 - (i - 11), (i - 16) * 5.0])
    assert 9 in offside_players(st, 0)
    st.pos[9] = np.array([-5.0, 0.0])
    assert 9 not in offside_players(st, 0)


def test_offside_receiver_gives_free_kick(cfg):
    st, rng = fresh(cfg)
    st.ball.owner = 5
    st.pos[9] = np.array([48.0, 0.0])
    release(st, BallCommand("pass", st.pos[9].copy(), "ground", 9), cfg, rng)
    assert 9 in st.ball.flight.offside
    gain_control(st, 9, cfg)
    assert st.restart is not None and st.restart.type == "free_kick" and st.restart.team == 1


def test_possession_events_on_turnover(cfg):
    st, _ = fresh(cfg)
    assert st.possession == 0
    gain_control(st, 15, cfg, cause="tackle")
    types = [(e.type, e.team) for e in st.events.events]
    assert ("possession_won", 1) in types and ("possession_lost", 0) in types and ("tackle_won", 1) in types


# -- whole-sim properties -------------------------------------------------------------------------


def test_deterministic_given_seed():
    lib = load_library()
    out = []
    for _ in range(2):
        env = MatchEnv(randomise=True)
        env.reset(7, Scenario(type="random_open_play"))
        r = env.run(RankingPolicy(lib, np.random.default_rng(3), temperature=0.02),
                    RankingPolicy(lib, np.random.default_rng(4), temperature=0.02), max_time_s=12)
        out.append((r.events, r.frames[-1]["p"], [p["play_id"] for p in r.plays]))
    assert out[0] == out[1]


def test_speed_at_least_20x_real_time():
    lib = load_library()
    env = MatchEnv(record_frames=False)
    env.reset(1, Scenario(type="mid_progression"))
    t0 = time.perf_counter()
    r = env.run(RankingPolicy(lib), RankingPolicy(lib), max_time_s=20, stop_on_turnover=False, stop_on_goal=False)
    wall = time.perf_counter() - t0
    assert r.duration_s / wall >= 20.0, f"{r.duration_s / wall:.1f}x real time"
