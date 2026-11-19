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


def tev(t, typ, team, **data):
    return {"t": t, "type": typ, "team": team, "data": data}


def test_trial_values_follow_each_objective():
    from soccersim.selfplay.objectives import trial_value

    kept = trial_value("keep_30", [tev(11.0, "possession_lost", 1)], 0, 0.0, 10.0, 6.0)
    lost_late = trial_value("keep_30", [tev(14.5, "possession_lost", 0)], 0, 0.0, 10.0, 6.0)
    lost_early = trial_value("keep_30", [tev(10.5, "possession_lost", 0)], 0, 0.0, 10.0, 6.0)
    assert kept == 1.0 > lost_late > lost_early > 0
    soon = trial_value("win_back_8", [tev(11.0, "possession_won", 1)], 1, 0.0, 10.0, 6.0)
    late = trial_value("win_back_8", [tev(15.0, "possession_won", 1)], 1, 0.0, 10.0, 6.0)
    assert soon > late > trial_value("win_back_8", [], 1, 0.0, 10.0, 6.0) == 0.0
    assert trial_value("protect_60", [tev(12, "goal", 1)], 0, 0.0, 10.0, 6.0) < \
        trial_value("protect_60", [tev(12, "shot_taken", 1, xg=0.3)], 0, 0.0, 10.0, 6.0) < 0
    assert trial_value("score_30", [tev(12, "goal", 0)], 0, 0.0, 10.0, 6.0) >= 1


def test_objective_teams_play_for_the_measured_objective():
    jobs = build_jobs(["lookahead_fast@objective"], ["possession"], ["keep_30", "win_back_8"], 2, ["fresh"])
    for j in jobs:
        mine = j["home"] if j["obj"]["side"] == 0 else j["away"]
        assert mine["objective"] == j["obj"]["objective"] and mine["kind"] == "lookahead"
        assert j["obj"]["team"] == "lookahead_fast@objective"


def test_blocked_shots_earn_no_credit():
    from soccersim.selfplay.objectives import trial_value
    from soccersim.selfplay.rewards import shot_credit_xg

    blocked = tev(12, "shot_taken", 0, xg=0.3, outcome="blocked")
    clear = tev(12, "shot_taken", 0, xg=0.3, outcome="off_target")
    assert shot_credit_xg(blocked) == 0.0 and shot_credit_xg(clear) == 0.3
    assert trial_value("score_30", [blocked], 0, 0.0, 10.0, 6.0) == 0.0


def test_current_objectives():
    from soccersim.selfplay.objectives import CURRENT, OBJECTIVES

    assert set(CURRENT) <= set(OBJECTIVES)
    assert success("score_120", [ev("goal", 0)], side=0)
    blocked = {"type": "shot_taken", "team": 0, "data": {"xg": 0.3, "outcome": "blocked"}}
    clear = {"type": "shot_taken", "team": 0, "data": {"xg": 0.3, "outcome": "caught"}}
    assert not success("chance_60", [blocked], side=0) and success("chance_60", [clear], side=0)
    assert success("chance_30", [blocked], side=0)  # the first set counted blocked shots
    assert success("win_back_30", [ev("possession_won", 0)], side=0)
    assert not success("protect_180", [ev("goal", 1)], side=0)
    jobs = build_jobs(["library"], ["possession"], ["keep_30", "win_back_30", "protect_180"], 2, ["fresh"])
    stop = {j["obj"]["objective"]: j["stop_on_turnover"] for j in jobs}
    assert stop == {"keep_30": True, "win_back_30": True, "protect_180": False}
    for j in jobs:
        if j["obj"]["objective"] == "protect_180":
            assert j["max_time_s"] == 180 and j["scenario"]["minute"] == 85


def test_agreed_objectives_and_targets():
    from soccersim.selfplay.objectives import CURRENT, TARGETS, markdown, summarise

    assert set(TARGETS) < set(CURRENT) and "score_180" not in TARGETS
    blocked = {"type": "shot_taken", "team": 0, "data": {"xg": 0.02, "outcome": "blocked"}}
    wide = {"type": "shot_taken", "team": 0, "data": {"xg": 0.02, "outcome": "off_target"}}
    assert not success("shot_60", [blocked], side=0) and success("shot_60", [wide], side=0)
    games = [{"objective": "keep_15", "condition": "fresh", "team": t, "opp": o, "k": k, "success": t == "x" or k == 0}
             for t in ("library", "x") for o in ("a", "b") for k in range(4)]
    md = markdown(summarise(games), 4)
    assert "| keep_15 | fresh | x |" in md and "75% | yes |" in md
