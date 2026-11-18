"""Objective success tests and job construction (soccersim/selfplay/objectives.py)."""

from soccersim.selfplay.objectives import build_jobs, cap_events, situations, success, wilson


def ev(t, team, **data):
    return {"type": t, "team": team, "data": data}


def test_success_tests():
    assert success("score_30", [ev("goal", 1)], side=1)
    assert not success("score_30", [ev("goal", 0)], side=1)
    assert success("chance_30", [ev("shot_taken", 0, xg=0.2)], side=0)
    assert not success("chance_30", [ev("shot_taken", 0, xg=0.05)], side=0)
    assert success("protect_60", [ev("goal", 0)], side=0)
    assert not success("protect_60", [ev("goal", 1)], side=0)
    assert not success("keep_30", [ev("possession_lost", 0)], side=0)
    assert success("keep_30", [ev("possession_lost", 1)], side=0)
    assert success("win_back_8", [ev("possession_won", 1)], side=1)


def test_situations_are_fixed_and_alternate_sides():
    a, b = situations("keep_30", 6), situations("keep_30", 6)
    assert a == b and [s["our_side"] for s in a] == [0, 1, 0, 1, 0, 1]


def test_jobs_set_up_the_situation_from_our_side():
    jobs = build_jobs(["library"], ["possession"], ["protect_60"], 2, ["fresh"])
    for j in jobs:
        side = j["obj"]["side"]
        sc = j["scenario"]
        assert sc["attacking_team"] == 1 - side  # they have the ball
        assert sc["score"][side] == 1 and sc["score"][1 - side] == 0
        assert (j["home"]["id"] if side == 0 else j["away"]["id"]) == "library"


def test_conditions_target_the_right_players():
    ev_ = cap_events("our_forwards_slow", 1, ("4-3-3", "4-4-2"))
    assert ev_ and all(11 <= e["player"] < 22 and e["substitute"] for e in ev_)
    ev_ = cap_events("their_defence_tiring", 1, ("4-3-3", "4-4-2"))
    assert ev_ and all(e["player"] < 11 and e["ramp_s"] > 0 for e in ev_)
    assert cap_events("fresh", 0, ("4-3-3", "4-3-3")) == []


def test_wilson_interval():
    p, lo, hi = wilson(5, 10)
    assert p == 0.5 and 0.2 < lo < 0.5 < hi < 0.8
