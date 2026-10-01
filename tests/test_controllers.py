"""M2: every action type's controller, demonstrated in a scenario (spec §7.3, §14).

Each test builds a one-step play around a single action, forces it through the real
pipeline (assignment -> executor -> controller -> physics) and checks the behaviour.
"""

from __future__ import annotations

import numpy as np
import pytest

from soccersim.controllers import REGISTRY
from soccersim.schema import load_library, parse_play
from soccersim.schema.vocab import ACTION_SPECS
from soccersim.sim.env import MatchEnv
from soccersim.sim.play_scenarios import run_play
from soccersim.sim.scenarios import Scenario

LIB = load_library()


def make_play(actions, roles, phase="in_possession", done="always_never", steps_extra=None, max_s=6.0):
    done_when = {"elapsed_s": {"gt": 999}} if done == "always_never" else done
    data = {
        "id": "ctrl_test", "phase": phase, "objective": "progress_ball" if "poss" in phase else "regain_possession",
        "roles": roles, "triggers": "always", "steps": [
            {"id": "s1", "actions": actions, "done_when": done_when, "timeout_s": max_s, "on_timeout": "next"},
            *(steps_extra or []),
        ],
        "success": {"elapsed_s": {"gt": 999}}, "abort": {"any": []}, "max_duration_s": max_s + 1,
    }
    return parse_play(data)


def run(play, scenario="mid_progression", attacking=0, seconds=4.0, seed=3):
    r = run_play(LIB, play.id, seed, Scenario(type=scenario, attacking_team=attacking, randomise_capabilities=False),
                 max_time_s=seconds, extra=play, ignore_triggers=True, env=MatchEnv())
    rec = r.forced_record(play.id)
    assert rec is not None, "forced play was not instantiated"
    return r.result, rec


BALL = {"id": "R1", "hints": ["CB_near", "DM", "CM", "FB_near", "W_near", "AM", "ST", "CB_far", "FB_far", "W_far"],
        "starts_with_ball": True}
MATE = {"id": "R2", "hints": ["CM", "AM", "W_near", "ST"]}
DEF = {"id": "D1", "hints": ["CM", "DM", "AM"]}


def last_act(res, p):
    """The player's most recent recorded directive [label, x, y]."""
    for f in reversed(res.frames):
        a = f["plays"]["acts0"].get(p)
        if a:
            return a
    raise AssertionError(f"no directive recorded for player {p}")


def pos_of(frame, p):
    return np.array(frame["p"][p])


def test_every_action_type_has_a_controller():
    assert set(ACTION_SPECS) <= set(REGISTRY)


# -- on-ball --------------------------------------------------------------------------------


@pytest.mark.parametrize("style", ["ground", "driven", "lofted", "through"])
def test_pass_releases_toward_receiver(style):
    play = make_play([{"role": "R1", "type": "pass", "to": {"role": "R2"}, "style": style}], [BALL, MATE])
    res, rec = run(play)
    kinds = [f["fl"][0] for f in res.frames if f["fl"]]
    assert "pass" in kinds
    assert any(e["type"] in ("pass_completed", "pass_intercepted") for e in res.events) or res.frames[-1]["o"] == -1
    if style == "lofted":
        assert any(f["bh"] == "air" for f in res.frames)


def test_cross_is_aerial_and_cutback_is_ground():
    play = make_play([{"role": "R1", "type": "cross", "to": {"role": "R2"}, "style": "lofted"}], [BALL, MATE])
    res, _ = run(play, "final_third_attack")
    assert any(f["bh"] == "air" for f in res.frames)
    play = make_play([{"role": "R1", "type": "cutback", "to": {"role": "R2"}}], [BALL, MATE])
    res, _ = run(play, "final_third_attack")
    assert any(f["fl"] for f in res.frames) and not any(f["bh"] == "air" for f in res.frames)


def test_clear_sends_the_ball_long():
    play = make_play([{"role": "R1", "type": "clear"}], [BALL])
    res, _ = run(play, seconds=4)
    assert any(f["fl"] and f["fl"][0] == "clear" for f in res.frames)


def test_distribute_from_keeper():
    gk = {"id": "GK", "hints": ["GK"], "starts_with_ball": True}
    play = make_play([{"role": "GK", "type": "distribute", "to": {"role": "R2"}, "style": "ground"}], [gk, MATE])
    res, rec = run(play, "build_up", seconds=5)
    assert any(f["fl"] and f["fl"][0] == "pass" for f in res.frames)


def test_carry_moves_ball_to_target():
    play = make_play([{"role": "R1", "type": "carry", "to": {"anchor": "ball", "offset": [10, 0]}, "speed": "fast"}],
                     [BALL])
    res, rec = run(play, seconds=4)
    p = rec["binding"]["R1"][0]
    start, end = res.frames[0]["b"], res.frames[-1]["b"]
    if res.frames[-1]["o"] == p:
        assert end[0] - start[0] > 6.0


def test_dribble_advances_and_avoids():
    play = make_play([{"role": "R1", "type": "dribble", "to": {"anchor": "ball", "offset": [12, 0]},
                       "beat": "nearest_to_ball"}], [BALL])
    res, rec = run(play, "final_third_attack", seconds=3)
    p = rec["binding"]["R1"][0]
    assert pos_of(res.frames[-1], p)[0] > pos_of(res.frames[0], p)[0] + 3


def test_shoot_takes_a_shot():
    play = make_play([{"role": "R1", "type": "shoot", "placement": "auto", "style": "placed"}], [BALL])
    res, _ = run(play, "final_third_attack", seconds=3)
    assert any(e["type"] == "shot_taken" for e in res.events)


def test_hold_up_keeps_the_ball():
    play = make_play([{"role": "R1", "type": "hold_up", "duration_s": 1.5}], [BALL],
                     done={"step_elapsed_s": {"gt": 1.6}})
    res, rec = run(play, seconds=1.5)
    p = rec["binding"]["R1"][0]
    held = [f["o"] == p for f in res.frames[:12]]
    assert sum(held) >= 8


# -- off-ball ---------------------------------------------------------------------------------


@pytest.mark.parametrize("atype", ["run_to", "third_man_run", "decoy_run", "hold_position"])
def test_runs_reach_target(atype):
    target = {"anchor": "ball", "offset": [8, -6]}
    play = make_play([{"role": "R2", "type": atype, "to": target}], [BALL, MATE])
    res, rec = run(play, seconds=5)
    p = rec["binding"]["R2"][0]
    acts = [f["plays"]["acts0"].get(p) for f in res.frames[:3]]
    tgt = next(np.array(a[1:]) for a in acts if a)
    assert np.hypot(*(pos_of(res.frames[-1], p) - tgt)) < 2.0


def test_run_to_arrive_with_slows_down_to_time_arrival():
    fast = make_play([{"role": "R2", "type": "run_to", "to": {"anchor": "goal", "offset": [-12, 0]}, "speed": "max"}],
                     [BALL, MATE])
    timed = make_play([
        {"role": "R1", "type": "carry", "to": {"anchor": "ball", "offset": [-2, 0]}, "speed": "jog"},
        {"role": "R2", "type": "run_to", "to": {"anchor": "goal", "offset": [-12, 0]}, "speed": "max",
         "arrive_with": "R1"}], [BALL, MATE])
    r1, rec1 = run(fast, seconds=1.5)
    r2, rec2 = run(timed, seconds=1.5)
    p1, p2 = rec1["binding"]["R2"][0], rec2["binding"]["R2"][0]
    d1 = np.hypot(*(pos_of(r1.frames[-1], p1) - pos_of(r1.frames[0], p1)))
    d2 = np.hypot(*(pos_of(r2.frames[-1], p2) - pos_of(r2.frames[0], p2)))
    assert d2 <= d1 + 1e-6


@pytest.mark.parametrize("atype,sign", [("overlap", 1), ("underlap", -1)])
def test_overlap_and_underlap_go_round_the_partner(atype, sign):
    w = {"id": "R1", "hints": ["W_near"], "starts_with_ball": True}
    fb = {"id": "R2", "hints": ["FB_near"]}
    play = make_play([{"role": "R1", "type": "hold_up", "duration_s": 6},
                      {"role": "R2", "type": atype, "around": "R1"}], [w, fb])
    res, rec = run(play, "final_third_attack", seconds=5)
    r1, r2 = rec["binding"]["R1"][0], rec["binding"]["R2"][0]
    a, b = pos_of(res.frames[-1], r1), pos_of(res.frames[-1], r2)
    assert b[0] > a[0]  # got beyond the partner


def test_spin_in_behind_stays_onside_until_the_pass():
    st = {"id": "R2", "hints": ["ST"]}
    play = make_play([{"role": "R1", "type": "hold_up", "duration_s": 4},
                      {"role": "R2", "type": "spin_in_behind", "line": "opp_last_line", "lane": "center", "depth": 8}],
                     [BALL, st])
    res, rec = run(play, seconds=3)
    p = rec["binding"]["R2"][0]
    for f in res.frames[5:]:
        opp_x = sorted(x for x, _ in f["p"][11:])
        assert f["p"][p][0] <= max(opp_x[-2], f["b"][0], 0.0) + 1.2


def test_check_to_ball_comes_short():
    play = make_play([{"role": "R2", "type": "check_to_ball", "distance": 6, "duration_s": 1.5}], [BALL, MATE])
    res, rec = run(play, seconds=2)
    p = rec["binding"]["R2"][0]
    d0 = np.hypot(*(pos_of(res.frames[0], p) - np.array(res.frames[0]["b"])))
    d1 = np.hypot(*(pos_of(res.frames[-1], p) - np.array(res.frames[-1]["b"])))
    assert d1 < d0 - 2.0


@pytest.mark.parametrize("angle", ["back_inside", "back_outside", "square", "forward"])
def test_support_takes_the_angle(angle):
    play = make_play([{"role": "R2", "type": "support", "from": "R1", "angle": angle, "distance": 10}], [BALL, MATE])
    res, rec = run(play, seconds=4)
    p = rec["binding"]["R2"][0]
    act = last_act(res, p)
    holder = pos_of(res.frames[-1], rec["binding"]["R1"][0])
    off = np.array(act[1:]) - holder
    if angle == "forward":
        assert off[0] > 5
    elif angle == "square":
        assert abs(off[0]) < 1.5
    else:
        assert off[0] < -4


def test_hold_width_goes_wide():
    play = make_play([{"role": "R2", "type": "hold_width", "lane": "far_wing"}], [BALL, MATE])
    res, rec = run(play, seconds=5)
    p = rec["binding"]["R2"][0]
    y0, y1 = pos_of(res.frames[0], p)[1], pos_of(res.frames[-1], p)[1]
    tgt = last_act(res, p)[2]
    assert abs(tgt) == 30.0 and abs(y1 - tgt) < abs(y0 - tgt) - 15


# -- defensive -------------------------------------------------------------------------------


def run_def(actions, roles, seconds=3.0, scenario="mid_progression"):
    play = make_play(actions, roles, phase="out_of_possession")
    return run(play, scenario, attacking=1, seconds=seconds)


def carrier(frame):
    return frame["o"] if frame["o"] >= 11 else None


@pytest.mark.parametrize("atype", ["press", "tackle"])
def test_press_and_tackle_close_down_the_carrier(atype):
    res, rec = run_def([{"role": "D1", "type": atype, "target": {"opponent": "ball_carrier"}}], [DEF])
    p = rec["binding"]["D1"][0]
    d0 = np.hypot(*(pos_of(res.frames[0], p) - np.array(res.frames[0]["b"])))
    d1 = min(np.hypot(*(pos_of(f, p) - np.array(f["b"]))) for f in res.frames)
    assert d1 < max(d0 - 4.0, 2.0)


def test_jockey_holds_off_goal_side():
    res, rec = run_def([{"role": "D1", "type": "jockey", "target": {"opponent": "ball_carrier"}}], [DEF], seconds=4)
    p = rec["binding"]["D1"][0]
    f = res.frames[-1]
    if carrier(f) is not None:
        c = pos_of(f, carrier(f))
        me = pos_of(f, p)
        assert 1.0 < np.hypot(*(me - c)) < 6.5 and me[0] < c[0] + 1.0


def test_mark_stays_goal_side_of_the_target():
    res, rec = run_def([{"role": "D1", "type": "mark", "target": {"opponent": "nearest_to_ball"}, "tightness": 2,
                         "goal_side": True}], [DEF], seconds=4)
    p = rec["binding"]["D1"][0]
    act = last_act(res, p)
    assert act[0] == "mark" and np.hypot(*(pos_of(res.frames[-1], p) - np.array(act[1:]))) < 4.5


def test_block_lane_sits_between_carrier_and_receiver():
    res, rec = run_def([{"role": "D1", "type": "block_lane", "from": "ball_carrier", "to": "nearest_receiver"}], [DEF])
    p = rec["binding"]["D1"][0]
    assert last_act(res, p)[0] == "block_lane"


def test_cover_and_block_shot_and_recover():
    d2 = {"id": "D2", "hints": ["CB_near", "CB_far"]}
    res, rec = run_def([{"role": "D1", "type": "press", "target": {"opponent": "ball_carrier"}},
                        {"role": "D2", "type": "cover", "behind": "D1", "depth": 8}], [DEF, d2])
    a, b = rec["binding"]["D1"][0], rec["binding"]["D2"][0]
    assert pos_of(res.frames[-1], b)[0] < pos_of(res.frames[-1], a)[0]
    res, rec = run_def([{"role": "D1", "type": "block_shot"}], [DEF], scenario="final_third_attack")
    p = rec["binding"]["D1"][0]
    act = last_act(res, p)
    assert act[1] < res.frames[-1]["b"][0]  # between the ball and our goal
    res, rec = run_def([{"role": "D1", "type": "recover", "speed": "max"}], [DEF])
    p = rec["binding"]["D1"][0]
    assert last_act(res, p)[1] < res.frames[-1]["b"][0]


@pytest.mark.parametrize("atype,params", [("compact_shift", {"line_height": 30, "width": 40, "ball_shift": 0.5}),
                                          ("hold_line", {"height": 30})])
def test_group_line_actions_form_a_line(atype, params):
    back = {"id": "G", "hints": ["CB_near", "CB_far", "FB_near", "FB_far"], "group": {"count": 4}}
    res, rec = run_def([{"role": "G", "type": atype, **params}], [back], seconds=5)
    xs = [pos_of(res.frames[-1], p)[0] for p in rec["binding"]["G"]]
    ys = sorted(pos_of(res.frames[-1], p)[1] for p in rec["binding"]["G"])
    assert np.ptp(xs) < 4.0 and abs(np.mean(xs) - (30 - 52.5)) < 4.0
    assert ys[-1] - ys[0] > 20


@pytest.mark.parametrize("mode", ["cover_line", "sweep"])
def test_keeper_set_position(mode):
    gk = {"id": "GK", "hints": ["GK"]}
    res, rec = run_def([{"role": "GK", "type": "set_position", "mode": mode}], [gk], seconds=3)
    p = rec["binding"]["GK"][0]
    act = last_act(res, p)
    assert act[1] < -40 if mode == "cover_line" else act[1] < -30
