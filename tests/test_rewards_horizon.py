"""Longer horizon: a play is credited with what the rest of its team's possession earned."""

from __future__ import annotations

import pytest

from soccersim.config import load_config
from soccersim.selfplay.rewards import assign_rewards, possession_spells


def _play(pid, t, team=0, epv=(0.0, 0.0), events=()):
    return {"play_id": pid, "team": team, "t_start": t, "epv_start": epv[0], "epv_end": epv[1], "events": list(events)}


PHASES = {"build": "in_possession", "shot": "in_possession", "press": "out_of_possession"}
OBJ = {"build": "progress_ball", "shot": "score", "press": "regain_possession"}


def test_setup_play_shares_the_credit_of_the_shot_that_follows():
    cfg = load_config("training")
    shot = {"type": "shot_taken", "team": 0, "pos": [40, 0], "data": {"xg": 0.3}}
    plays = [_play("build", 0.0, epv=(0.01, 0.01)), _play("shot", 3.0, epv=(0.01, 0.0), events=[shot])]
    assign_rewards(plays, PHASES, OBJ, cfg)
    g, xgw = cfg["rewards"]["gamma_per_play"], cfg["rewards"]["shot_xg"]
    assert plays[1]["reward"] == pytest.approx(-0.01 + xgw * 0.3, abs=1e-6)
    assert plays[0]["reward"] == pytest.approx(0.0, abs=1e-6)  # the set-up play alone earns nothing
    assert plays[0]["possession_return"] == pytest.approx(g * plays[1]["reward"], abs=1e-6)


def test_possession_ends_when_the_team_loses_the_ball_or_a_goal_falls():
    goal = {"type": "goal", "team": 0, "pos": [52, 0]}
    seq = [_play("build", 0), _play("shot", 1, events=[goal]), _play("build", 2), _play("press", 3), _play("build", 4)]
    spells = possession_spells(seq, PHASES)
    assert [[p["t_start"] for p in s] for s in spells] == [[0, 1], [2], [3], [4]]


def test_an_opponent_shot_counts_against_the_defending_play():
    cfg = load_config("training")
    shot = {"type": "shot_taken", "team": 1, "pos": [-40, 0], "data": {"xg": 0.2}}
    plays = [_play("press", 0.0, events=[shot])]
    assign_rewards(plays, PHASES, OBJ, cfg)
    assert plays[0]["reward"] == pytest.approx(-cfg["rewards"]["shot_xg"] * 0.2, abs=1e-6)
