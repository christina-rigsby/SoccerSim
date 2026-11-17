"""The law fixes of docs/REALISM.md: pressure on the passer, blocked shots, fatigue, capability changes."""

from __future__ import annotations

import copy

import numpy as np
import pytest

from soccersim.config import load_config
from soccersim.sim import shots
from soccersim.sim.ball import BallCommand, release, step_ball
from soccersim.sim.fatigue import update
from soccersim.sim.passmodel import noisy_target
from soccersim.sim.physics import max_speed
from soccersim.sim.scenarios import Scenario, build_state, setup_scenario
from soccersim.sim.state import CAP_INDEX


@pytest.fixture(scope="module")
def cfg():
    return load_config("sim")


def fresh(cfg, seed=0, **kw):
    rng = np.random.default_rng(seed)
    sc = Scenario(type="mid_progression", randomise_capabilities=False, **kw)
    st = build_state(rng, sc, cfg)
    setup_scenario(st, sc, rng, cfg)
    return st, rng


def test_pressure_adds_aim_error_even_for_a_perfect_passer(cfg):
    rng = np.random.default_rng(0)
    o, t = np.zeros(2), np.array([20.0, 0.0])
    free = [np.hypot(*(noisy_target(rng, o, t, "ground", 1.0, 0.0, cfg) - t)) for _ in range(400)]
    pressed = [np.hypot(*(noisy_target(rng, o, t, "ground", 1.0, 0.6, cfg) - t)) for _ in range(400)]
    assert np.mean(free) < 1e-9
    assert np.mean(pressed) > 1.0


def test_block_probability_falls_off_the_line(cfg):
    s, tgt = np.array([36.0, 0.0]), np.array([53.0, 0.0])
    p = shots.block_probabilities(s, tgt, np.array([[42.0, 0.0], [42.0, 2.0], [42.0, 6.0], [35.0, 0.0]]), cfg)
    assert p[0] == pytest.approx(cfg["shot"]["block"]["max_prob"])
    assert p[0] > p[1] > p[2] >= 0
    assert p[3] == 0  # behind the shooter


def test_shot_through_a_defender_can_be_blocked(cfg):
    blocked = 0
    for k in range(60):
        st, rng = fresh(cfg, k)
        for i in range(12, 22):
            st.pos[i] = np.array([40.0 + i * 0.3, 33.0])
        st.pos[11] = np.array([51.0, 0.0])
        shooter = 9
        st.pos[shooter] = np.array([36.0, 0.0])
        st.pos[12] = np.array([42.0, 0.0])
        st.restart = None
        st.ball.owner, st.ball.flight, st.ball.pos = shooter, None, st.pos[shooter].copy()
        n = len(st.events.events)
        release(st, BallCommand("shoot", np.array([52.5, 0.0]), "shot", -1), cfg, rng)
        for _ in range(20):
            st.t += 0.1
            step_ball(st, cfg, rng, 0.1)
        types = [e.type for e in st.events.events[n:]]
        if "shot_blocked" in types:
            blocked += 1
            assert "goal" not in types
            assert st.ball.last_touch_team == 1 or st.ball.owner >= 0
    assert 10 <= blocked <= 50


def test_fatigue_grows_with_work_and_slows_players(cfg):
    st, _ = fresh(cfg, fatigue=0.0)
    v0 = max_speed(st, cfg).copy()
    frac = np.zeros(22)
    frac[5], frac[6] = 1.0, 0.4
    for _ in range(3000):
        update(st, frac, cfg, 0.1)
    assert st.fatigue[5] > 3 * st.fatigue[6] > 0
    assert st.fatigue[7] == 0
    v = max_speed(st, cfg)
    assert v[5] < 0.98 * v0[5] and v[7] == pytest.approx(v0[7])
    assert st.caps[5, CAP_INDEX["passing"]] < st.caps_base[5, CAP_INDEX["passing"]]


def test_scenarios_start_with_the_fatigue_of_their_minute(cfg):
    early, _ = fresh(cfg, 1, minute=5.0)
    late, _ = fresh(cfg, 1, minute=85.0)
    assert late.fatigue.mean() > 5 * early.fatigue.mean()
    assert (late.caps <= late.caps_base + 1e-12).all()


def test_fatigue_off_keeps_fresh_capabilities(cfg):
    off = copy.deepcopy(cfg)
    off["fatigue"]["enabled"] = False
    st, _ = fresh(off, 2, minute=85.0)
    assert np.allclose(st.caps, st.caps_base) and st.fatigue.max() == 0


def test_gradual_change_and_substitution(cfg):
    events = [{"t": 1.0, "player": 9, "caps": {"pace": 0.2}, "ramp_s": 2.0},
              {"t": 1.0, "player": 10, "substitute": True, "caps": {"pace": 0.95}}]
    st, _ = fresh(cfg, 3, minute=80.0, cap_events=events)
    p0 = st.caps_base[9, CAP_INDEX["pace"]]
    assert st.fatigue[10] > 0
    frac = np.zeros(22)
    while st.t < 2.0 - 1e-9:
        st.t += 0.1
        update(st, frac, cfg, 0.1)
    assert st.caps_base[9, CAP_INDEX["pace"]] == pytest.approx((p0 + 0.2) / 2, abs=0.02)
    assert st.caps_base[10, CAP_INDEX["pace"]] == pytest.approx(0.95)
    assert st.fatigue[10] == 0 and st.stamina[10] == 1.0
    assert [e.type for e in st.events.events].count("substitution") == 1
    while st.t < 4.0:
        st.t += 0.1
        update(st, frac, cfg, 0.1)
    assert st.caps_base[9, CAP_INDEX["pace"]] == pytest.approx(0.2)
    assert [e.type for e in st.events.events].count("substitution") == 1
