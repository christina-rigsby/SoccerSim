"""M5: Module 2 — candidates, hard gate, Hungarian assignment, scoring, preemption, and a
full scripted match end to end with the replay viewer (spec §9, §14)."""

from __future__ import annotations

import numpy as np
import pytest

from soccersim.dashboard.team_state import Context, TeamView
from soccersim.ranking import RankingPolicy, assign, graph_path_value, score_play
from soccersim.ranking.selector import Candidate
from soccersim.schema import load_library, parse_play, play_to_dict
from soccersim.sim.env import MatchEnv
from soccersim.sim.scenarios import Scenario
from soccersim.sim.state import CAP_INDEX
from soccersim.viz.replay_html import export_replay_html

LIB = load_library()
CTX = Context()


def view(typ="mid_progression", seed=0, team=0, attacking=0):
    env = MatchEnv()
    env.reset(seed, Scenario(type=typ, attacking_team=attacking, randomise_capabilities=False))
    return env, TeamView(env.state, team, CTX)


def test_assignment_binds_ball_role_to_holder_and_respects_requires():
    env, v = view("final_third_attack")
    pol = RankingPolicy(LIB)
    play = LIB["wide_overlap_cross"]
    asg = assign(play, v, v.side_from_ball(), pol.cfg)
    if asg.feasible:
        assert asg.binding["R1"] == [v.holder]
        bound = [p for ps in asg.binding.values() for p in ps]
        assert len(bound) == len(set(bound)) == 5
    # Make every outfielder too slow for R2 (pace >= 0.5): infeasible.
    env.state.caps[:11, CAP_INDEX["pace"]] = 0.2
    asg = assign(play, TeamView(env.state, 0, CTX), v.side_from_ball(), pol.cfg)
    assert not asg.feasible and "R" in asg.reason


def test_keeper_only_fills_keeper_roles():
    _, v = view()
    pol = RankingPolicy(LIB)
    asg = assign(LIB["low_block_box_protection"], v, 1.0, pol.cfg)
    assert asg.feasible
    gk = v.state.gk(0)
    assert asg.binding["GK"] == [gk]
    assert all(gk not in ps for r, ps in asg.binding.items() if r != "GK")
    assert sorted(len(ps) for ps in asg.binding.values()) == [1, 1, 1, 4, 4]


def test_assignment_prefers_hinted_players():
    _, v = view(attacking=1)
    pol = RankingPolicy(LIB)
    asg = assign(LIB["counterpress_five_seconds"], v, 1.0, pol.cfg)
    hints = {v.hint_of(p, 1.0) for p in asg.binding["REST"]}
    assert hints <= {"CB_near", "CB_far", "FB_far", "FB_near", "DM"}


def test_score_components_sum_and_game_state_modifiers():
    _, v = view("final_third_attack")
    pol = RankingPolicy(LIB)
    play = LIB["recycle_possession"]
    asg = assign(play, v, v.side_from_ball(), pol.cfg)
    score, comp = score_play(play, v, asg, pol.cfg)
    assert score == pytest.approx(sum(comp.values()), abs=1e-4)
    assert comp["chain_depth"] == pytest.approx(-0.005 * play.soft_hints.chain_depth)
    chance = LIB["wide_overlap_cross"]
    early = graph_path_value(chance, -1, 20.0, pol.cfg)
    late = graph_path_value(chance, -1, 85.0, pol.cfg)
    assert late > early


def test_decide_logs_all_candidates_and_respects_phase():
    _, v = view()
    pol = RankingPolicy(LIB)
    inst = pol.decide(v, "start")
    rec = pol.last_decision
    assert inst is not None and rec["chosen"] == inst.play.id
    phases = {LIB[c["play_id"]].phase for c in rec["candidates"]}
    assert phases <= {"in_possession", "transition_attack", "set_piece"}
    assert any(c["feasible"] for c in rec["candidates"])
    for c in rec["candidates"]:
        assert set(c) >= {"play_id", "source", "feasible", "reason", "score", "components"}


def test_preemption_hysteresis_and_cooldown():
    _, v = view()
    pol = RankingPolicy(LIB)
    inst = pol.decide(v, "start")
    v2 = TeamView(v.state, 0, CTX, active_plays={0: inst})
    # Same best play on interrupt: keep the active one.
    assert pol.decide(v2, "interrupt") is None and pol.last_decision["kept_active"]
    # A hugely better candidate preempts; one inside the margin does not.
    inst.score = -1.0
    new = pol.decide(v2, "interrupt")
    assert new is None or new.play.id != inst.play.id or pol.last_decision["kept_active"]
    pol.cooldowns["recycle_possession"] = v.t + 5
    pol.decide(TeamView(v.state, 0, CTX), "start")
    reasons = {c["play_id"]: c["reason"] for c in pol.last_decision["candidates"]}
    assert reasons["recycle_possession"] == "cooldown"


def test_softmax_sampling_is_seeded():
    cands = [Candidate(LIB[p], True, score=s) for p, s in (("recycle_possession", 0.01), ("switch_of_play", 0.02))]
    picks = []
    for _ in range(2):
        pol = RankingPolicy(LIB, rng=np.random.default_rng(5), temperature=0.01)
        picks.append([pol._select(cands).play.id for _ in range(30)])
    assert picks[0] == picks[1] and len(set(picks[0])) == 2
    assert RankingPolicy(LIB, temperature=0.0)._select(cands).play.id == "switch_of_play"


class StubGenerator:
    """Proposes one shooting play — stands in for Module 3."""

    def __init__(self):
        data = play_to_dict(LIB["recycle_possession"])
        data.update(id="gen_shoot", source="generated", fallback=False, objective="score", strategy="generated")
        data["steps"] = [{"id": "s1", "actions": [{"role": "R1", "type": "shoot"}],
                          "done_when": {"event": "shot_taken"}, "timeout_s": 2}]
        data["success"] = {"event": "shot_taken"}
        self.play = parse_play(data)
        self.calls = 0

    def sample(self, obs, n):
        self.calls += 1
        return [self.play]


def test_generator_on_gap_only_and_competes_in_same_ranking():
    _, v = view("final_third_attack")
    gen = StubGenerator()
    pol = RankingPolicy(LIB, generator=gen)
    pol.cfg["generator"]["enabled"] = True
    pol.cfg["generator"]["threshold"] = -1.0           # library never has a gap
    pol.decide(v, "start")
    real = [c for c in pol.last_decision["candidates"]
            if c["feasible"] and c["source"] == "library" and not LIB[c["play_id"]].fallback]
    # Consulted exactly when no non-fallback library play is feasible.
    assert gen.calls == (0 if real else 1) == int(pol.last_decision["generator_used"])
    gen.calls = 0
    pol.cfg["generator"]["threshold"] = 1.0            # every library score is under threshold
    inst = pol.decide(v, "start")
    assert gen.calls == 1 and pol.last_decision["library_gap"] and pol.last_decision["generator_used"]
    ids = [c["play_id"] for c in pol.last_decision["candidates"]]
    assert "gen_shoot" in ids and inst.play.id == "gen_shoot"  # objective=score outranks recycling


def test_full_scripted_match_end_to_end(tmp_path):
    """Full-match mode: no stopping on goals or turnovers; restarts and kickoffs keep it going."""
    env = MatchEnv()
    env.reset(3, Scenario(type="kickoff"))
    r = env.run(RankingPolicy(LIB, rng=np.random.default_rng(1)), RankingPolicy(LIB, rng=np.random.default_rng(2)),
                max_time_s=150, stop_on_goal=False, stop_on_turnover=False)
    assert r.duration_s == pytest.approx(150, abs=0.11)
    assert len(r.frames) == 1500
    ids = {p["play_id"] for p in r.plays}
    assert len(ids) >= 4                      # plays are being selected...
    assert any(p["end_reason"] for p in r.plays)  # ...and executed to an end
    assert {d["reason"] for d in r.decisions} >= {"interrupt", "possession_change"}
    out = export_replay_html([r], tmp_path / "match.html", ["full match"])
    html = out.read_text()
    assert "<canvas" in html and '"plays"' in html and "full match" in html
