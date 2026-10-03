"""M4: the play executor — every starter play runs in a scenario where its triggers hold,
logs are well formed, and possession plays mirror across the ball side (spec §5, §6.13)."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
import pytest

from soccersim.dashboard.team_state import Context, TeamView
from soccersim.executor import END_REASONS, PlayInstance
from soccersim.ranking import assign
from soccersim.ranking.selector import RankingPolicy
from soccersim.schema import load_library, parse_play
from soccersim.schema.vocab import POSSESSION_PHASES
from soccersim.sim.env import MatchEnv
from soccersim.sim.play_scenarios import run_play
from soccersim.sim.restarts import execute_restart
from soccersim.sim.scenarios import Scenario

LIB = load_library(promoted_runs=())  # hand-written plays: each has a pinned scenario
PINNED = json.loads((Path(__file__).parent / "fixtures" / "play_scenarios.json").read_text())
CTX = Context()

PLAY_KEYS = {"play_id", "source", "team", "side", "binding", "t_start", "t_end", "duration_s", "end_reason",
             "steps_visited", "epv_start", "epv_end", "events", "decision", "opp_play_at_start", "opp_play_at_end"}


def test_every_play_has_a_pinned_scenario():
    assert set(PINNED) == set(LIB)


@pytest.mark.parametrize("play_id", sorted(LIB))
def test_starter_play_runs_to_an_end_reason(play_id):
    pin = PINNED[play_id]
    sc = Scenario(**{k: v for k, v in pin["scenario"].items() if k != "score"}, score=tuple(pin["scenario"]["score"]))
    run = run_play(LIB, play_id, pin["seed"], sc)
    rec = run.forced_record(play_id)
    assert rec is not None, f"{play_id} was not instantiated by its own triggers"
    assert rec["end_reason"] in END_REASONS
    assert PLAY_KEYS <= set(rec)
    assert rec["steps_visited"] and rec["steps_visited"][0] == LIB[play_id].steps[0].id
    assert all(isinstance(v, list) and v for v in rec["binding"].values())
    assert rec["decision"]["chosen"] == play_id
    json.dumps(rec)  # serialisable
    # Deterministic: the pinned end reason reproduces.
    assert rec["end_reason"] == pin["end_reason"]


# -- mirror test ------------------------------------------------------------------------------


def _possession_state(play):
    env = MatchEnv()
    typ = "build_up" if play.phase == "set_piece" else "final_third_attack"
    if "ball_beyond_line" in json.dumps(play.triggers):
        # Build-up plays only start before a line is broken; in a final-third state their
        # success already holds and they would end before issuing any directive.
        typ = "mid_progression"
    env.reset(11, Scenario(type=typ, randomise_capabilities=False))
    st = env.state
    if st.restart is not None:
        execute_restart(st, env.cfg)
    if abs(st.ball.pos[1]) < 3.0:
        # Keep the frozen side unambiguous.
        st.ball.pos[1] = 6.0
        st.pos[st.ball.owner] = st.ball.pos
    return st


def _mirror(st):
    m = copy.deepcopy(st)
    for arr in (m.pos, m.vel, m.base_out, m.base_in):
        arr[:, 1] *= -1
    m.ball.pos = m.ball.pos * np.array([1.0, -1.0])
    return m


def _first_directives(play, st):
    view = TeamView(st, 0, CTX)
    side = view.side_from_ball()
    asg = assign(play, view, side, RankingPolicy(LIB).cfg)
    assert asg.feasible, asg.reason
    inst = PlayInstance(play, 0, side, asg.binding, view)
    dirs = inst.tick(TeamView(st, 0, CTX, active_plays={0: inst}))
    return side, asg.binding, {p: d.target for p, d in dirs.items()}


@pytest.mark.parametrize("play_id", sorted(p for p in LIB if LIB[p].phase in POSSESSION_PHASES))
def test_mirror_image_targets(play_id):
    play = LIB[play_id]
    st = _possession_state(play)
    s1, b1, t1 = _first_directives(play, st)
    s2, b2, t2 = _first_directives(play, _mirror(st))
    assert s1 == -s2
    assert b1 == b2
    assert set(t1) == set(t2) and t1
    for p in t1:
        assert np.allclose(t1[p], t2[p] * np.array([1.0, -1.0]), atol=0.5), (p, t1[p], t2[p])


# -- step machine -------------------------------------------------------------------------------


def _mini(steps, success=None, abort=None, max_s=10.0):
    return parse_play({
        "id": "mini", "phase": "in_possession", "objective": "retain_possession",
        "roles": [{"id": "R1", "hints": ["CB_near", "CM", "DM", "FB_near", "W_near", "AM", "ST"],
                   "starts_with_ball": True}, {"id": "R2", "hints": ["CM", "AM"]}],
        "steps": steps, "success": success or {"elapsed_s": {"gt": 99}}, "abort": abort or {"any": []},
        "max_duration_s": max_s,
    })


def _run(play, seconds=6.0):
    r = run_play(LIB, play.id, 2, Scenario(type="mid_progression", randomise_capabilities=False),
                 max_time_s=seconds, extra=play, ignore_triggers=True, env=MatchEnv())
    return r.forced_record(play.id)


def test_on_timeout_next_and_completed():
    hold = {"role": "R1", "type": "hold_up", "duration_s": 9}
    play = _mini([
        {"id": "a", "actions": [hold], "done_when": {"elapsed_s": {"gt": 99}}, "timeout_s": 0.5, "on_timeout": "next"},
        {"id": "b", "actions": [hold], "done_when": "always"},
    ])
    rec = _run(play)
    assert rec["steps_visited"] == ["a", "b"] and rec["end_reason"] == "completed"


def test_on_timeout_abort_and_goto():
    hold = {"role": "R1", "type": "hold_up", "duration_s": 9}
    play = _mini([{"id": "a", "actions": [hold], "done_when": {"elapsed_s": {"gt": 99}}, "timeout_s": 0.5}])
    assert _run(play)["end_reason"] == "step_timeout_abort"
    play = _mini([
        {"id": "a", "actions": [hold], "done_when": {"elapsed_s": {"gt": 99}}, "timeout_s": 0.4,
         "on_timeout": "goto:c"},
        {"id": "b", "actions": [hold], "done_when": "always"},
        {"id": "c", "actions": [hold], "done_when": "always", "next": "end"},
    ])
    assert _run(play)["steps_visited"] == ["a", "c"]


def test_success_abort_and_max_duration():
    hold = {"role": "R1", "type": "hold_up", "duration_s": 9}
    step = [{"id": "a", "actions": [hold], "done_when": {"elapsed_s": {"gt": 99}}, "timeout_s": 50}]
    assert _run(_mini(step, success={"elapsed_s": {"gt": 0.5}}))["end_reason"] == "success"
    assert _run(_mini(step, abort={"elapsed_s": {"gt": 0.5}}))["end_reason"] == "abort"
    assert _run(_mini(step, max_s=1.0))["end_reason"] == "timeout"


def test_start_when_waits_and_choose_is_evaluated_once():
    hold = {"role": "R1", "type": "hold_up", "duration_s": 9}
    play = _mini([
        {"id": "a", "start_when": {"elapsed_s": {"gt": 1.0}},
         "choose": [{"when": {"step_elapsed_s": {"lt": 0.05}}, "actions": [hold]},
                    {"when": "always", "actions": [{"role": "R1", "type": "shoot"}]}],
         "done_when": {"step_elapsed_s": {"gt": 1.5}}, "timeout_s": 5},
    ])
    rec = _run(play, 4.0)
    assert rec["steps_visited"] == ["a"]
    assert not any(e["type"] == "shot_taken" for e in rec["events"])  # first option was frozen at step start


def test_possession_change_ends_possession_plays():
    play = _mini([{"id": "a", "actions": [{"role": "R1", "type": "pass", "to": {"anchor": "own_goal",
                                                                               "offset": [80, 30]}}],
                   "done_when": {"elapsed_s": {"gt": 99}}, "timeout_s": 50}])
    r = run_play(LIB, "mini", 2, Scenario(type="mid_progression", randomise_capabilities=False), max_time_s=12,
                 extra=play, ignore_triggers=True, env=MatchEnv())
    rec = r.forced_record("mini")
    assert rec["end_reason"] in ("possession_change", "timeout")
