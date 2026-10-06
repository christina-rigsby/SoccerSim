"""M7–M9: tokenizer/grammar, generator, critic, PPO, archive, league bookkeeping (spec §10–11)."""

from __future__ import annotations

import numpy as np
import pytest

from soccersim.eval.elo import Elo, Payoff
from soccersim.generator.grammar import VOCAB_SIZE, detokenize, play_program
from soccersim.generator.mutate import OPERATORS, apply_operator, mutate
from soccersim.generator.tokenizer import TokenizeError, tokenize_play
from soccersim.schema import load_library, parse_play, play_to_dict
from soccersim.selfplay.pfsp import pfsp_weights
from soccersim.selfplay.qd_archive import Archive, descriptor, n_passes
from soccersim.selfplay.rewards import assign_rewards

LIB = load_library()


def random_walk(seed: int):
    rng = np.random.default_rng(seed)
    prog = play_program()
    allowed = next(prog)
    toks = []
    try:
        while True:
            t = int(rng.choice(sorted(allowed)))
            toks.append(t)
            allowed = prog.send(t)
    except StopIteration as stop:
        return toks, stop.value


def test_grammar_walks_are_always_schema_valid():
    for seed in range(300):
        toks, play = random_walk(seed)
        assert len(toks) <= 320
        parse_play({**play, "id": f"walk_{seed}"})
        assert detokenize(toks)["steps"] == play["steps"]


def test_off_grammar_tokens_are_rejected():
    toks, _ = random_walk(1)
    bad = list(toks)
    bad[3] = bad[1]  # a PHASE token where TEMPO belongs
    with pytest.raises(ValueError):
        detokenize(bad)
    with pytest.raises(ValueError):
        detokenize(toks[:-3])


@pytest.mark.parametrize("pid", sorted(p for p in LIB if LIB[p].phase in ("in_possession", "transition_attack",
                                                                            "set_piece")))
def test_possession_library_plays_tokenize(pid):
    toks = tokenize_play(LIB[pid])
    play = parse_play(detokenize(toks))
    assert play.source == "generated" and len(play.roles) == len(LIB[pid].roles)
    assert play.roles[0].starts_with_ball


def test_defensive_plays_are_not_tokenized():
    with pytest.raises(TokenizeError):
        tokenize_play(LIB["mid_block_compact"])


def test_mutation_operators_produce_valid_plays():
    rng = np.random.default_rng(0)
    made = 0
    for _ in range(80):
        m = mutate(LIB["wide_overlap_cross"], rng)
        if m is not None:
            made += 1
            assert m.source == "generated" and m.provenance["parent"] == "wide_overlap_cross"
    assert made > 40
    for op in OPERATORS:
        d = play_to_dict(LIB["third_man_combination"])
        apply_operator(d, op, np.random.default_rng(3))


def test_rewards_goals_regain_and_discount():
    plays = [
        {"play_id": "a", "team": 0, "t_start": 0.0, "epv_start": 0.01, "epv_end": 0.05, "events": []},
        {"play_id": "b", "team": 0, "t_start": 5.0, "epv_start": 0.05, "epv_end": 0.0,
         "events": [{"type": "goal", "team": 0, "pos": [50, 0]}]},
        {"play_id": "d", "team": 1, "t_start": 0.0, "epv_start": -0.05, "epv_end": 0.0,
         "events": [{"type": "possession_won", "team": 1, "pos": [0, 0]}]},
    ]
    assign_rewards(plays, {"a": "in_possession", "b": "in_possession", "d": "out_of_possession"},
                   {"a": "progress_ball", "b": "score", "d": "regain_possession"})
    assert plays[0]["reward"] == pytest.approx(0.04)
    assert plays[1]["reward"] == pytest.approx(1.0 - 0.05)
    assert plays[0]["return"] == pytest.approx(0.04 + 0.97 * plays[1]["reward"])
    assert plays[2]["reward"] == pytest.approx(0.05 + 0.02)


def test_retain_possession_farming_is_capped():
    plays = [{"play_id": "r", "team": 0, "t_start": float(i), "epv_start": 0.02, "epv_end": 0.02,
              "events": [{"type": "possession_won", "team": 0, "pos": [0, 0]}]} for i in range(10)]
    assign_rewards(plays, {"r": "out_of_possession"}, {"r": "retain_possession"})
    assert sum(p["reward"] for p in plays) <= 0.02 + 1e-9


def test_archive_cells_and_elites():
    toks, d = random_walk(5)
    d["id"] = "g1"
    a = Archive(min_evals=2)
    st = {"ball": [30.0, 25.0]}
    desc = descriptor(d, st, 1.0)
    assert desc[0] == "final_third" and desc[1] == "near_wing" and desc[3] == n_passes(d)
    a.add(d, desc, 0.1, "x")
    assert a.coverage()["elite_cells"] == 0 and a.under_evaluated(3) == ["g1"]
    a.add(d, desc, 0.2, "y")
    assert a.elites() == ["g1"] and a.stats("g1")["mean"] == pytest.approx(0.15)


def test_elo_payoff_and_pfsp():
    elo, pay = Elo(), Payoff()
    for _ in range(5):
        elo.update("main", "weak", 1.0)
        pay.add("main", "weak", 1.0, 0.1)
        elo.update("main", "strong", 0.0)
        pay.add("main", "strong", 0.0, -0.1)
    assert elo.get("main") > elo.get("weak") and elo.get("strong") > elo.get("main")
    w = pfsp_weights("main", ["weak", "strong", "new"], pay)
    assert w[1] > w[2] > w[0]


torch = pytest.importorskip("torch")


def test_generator_samples_are_valid_and_logprobs_match():
    from soccersim.generator.encoder import NODE_DIM
    from soccersim.generator.model import PlayGenerator, grammar_masks, pad_batch

    torch.manual_seed(0)
    gen = PlayGenerator({"hidden": 16, "layers": 1, "heads": 2}, d_model=32, layers=1, heads=2)
    gen.eval()
    x = torch.randn(1, 23, NODE_DIM)
    h = torch.tensor([3])
    samples = gen.sample(x, h, 4, 1.0, torch.Generator().manual_seed(1))
    for s in samples:
        parse_play({**s.play, "id": "s"})
    seqs = [s.tokens for s in samples]
    lp = gen.sequence_logprob(x.expand(4, -1, -1), h.expand(4), pad_batch(seqs), [grammar_masks(t) for t in seqs])
    assert np.allclose(lp.detach().numpy(), [s.logprob for s in samples], atol=1e-3)
    assert gen.head.out_features == VOCAB_SIZE


def test_critic_forward_and_ppo_step():
    from soccersim.generator.critic import Critic
    from soccersim.generator.encoder import NODE_DIM
    from soccersim.generator.model import PlayGenerator
    from soccersim.generator.ppo import critic_baseline, ppo_update

    torch.manual_seed(0)
    gen = PlayGenerator({"hidden": 16, "layers": 1, "heads": 2}, d_model=32, layers=1, heads=2)
    ref = PlayGenerator({"hidden": 16, "layers": 1, "heads": 2}, d_model=32, layers=1, heads=2)
    ref.load_state_dict(gen.state_dict())
    gen.eval()
    rolls = []
    for k in range(6):
        x = torch.randn(1, 23, NODE_DIM)
        s = gen.sample(x, torch.tensor([2]), 1, 1.0, torch.Generator().manual_seed(k))[0]
        rolls.append({"x": x[0].numpy().astype(np.float16), "holder": 2, "tokens": s.tokens, "logprob": s.logprob,
                      "reward": float(k % 2)})
    critic = Critic(13, {"hidden": 16, "layers": 1, "heads": 2}, d=16, layers=1, heads=2)
    base = critic_baseline(critic, rolls, 12)
    assert base.shape == (6,)
    opt = torch.optim.Adam(gen.parameters(), lr=1e-3)
    stats = ppo_update(gen, ref, rolls, base, {"epochs": 2, "clip": 0.2, "kl_beta": 0.05}, opt, batch=3)
    assert stats["n"] == 6 and abs(stats["ratio"] - 1.0) < 0.5


def test_promotion_run_numbers(tmp_path):
    import json

    from soccersim.selfplay.promote import promotion_run, run_numbers

    root = tmp_path / "promoted"
    (root / "run_1").mkdir(parents=True)
    (root / "run_3").mkdir()
    (root / "notes").mkdir()
    league = tmp_path / "league"
    league.mkdir()
    (league / "state.json").write_text(json.dumps({"update": 6}))
    assert run_numbers(root) == [1, 3]
    assert promotion_run(league, root) == 4
    (root / "run_4").mkdir()
    assert promotion_run(league, root) == 4  # the same league keeps its run number
    assert json.loads((league / "state.json").read_text())["update"] == 6


# -- run lineage (options 1-4) ---------------------------------------------------------------


def _fake_run(models, n, gate=None, continued_from=None, pool=None):
    import json

    from soccersim.config import load_config
    from soccersim.selfplay.runs import pool_definition

    d = models / "runs" / f"run_{n}"
    d.mkdir(parents=True)
    (d / "main.pt").write_text("main")
    (d / "start.pt").write_text("start")
    state = {"run": n, "pool": pool or pool_definition(load_config("league")), "continued_from": continued_from}
    if gate is not None:
        state["gate"] = {"passed": gate}
    (d / "state.json").write_text(json.dumps(state))
    return d


def test_plan_start_guardrails(tmp_path):
    from soccersim.config import load_config
    from soccersim.selfplay.runs import plan_start

    lc = load_config("league")
    models = tmp_path / "models"
    models.mkdir()
    assert plan_start(models, lc)["continued_from"] is None  # first run
    d1 = _fake_run(models, 1, gate=True)
    p = plan_start(models, lc)
    assert p["continued_from"] == 1 and p["start_from"] == str(d1 / "main.pt")
    assert plan_start(models, lc, "fresh")["continued_from"] is None
    # A changed opponent pool blocks continuation (unless forced).
    changed = {**lc, "pfsp_weighting": "linear"}
    p = plan_start(models, changed)
    assert p["continued_from"] is None and "pfsp_weighting" in p["reason"]
    assert plan_start(models, changed, "force")["continued_from"] == 1
    # A failed gate on a continued run falls back to the generator that run started from.
    d2 = _fake_run(models, 2, gate=False, continued_from=1)
    p = plan_start(models, lc)
    assert p["start_from"] == str(d2 / "start.pt") and p["continued_from"] == 1
    # A failed gate on a run that started fresh means start fresh again.
    _fake_run(models, 3, gate=False, continued_from=None)
    assert plan_start(models, lc)["continued_from"] is None
    # No gate result: do not continue.
    _fake_run(models, 4, gate=None)
    assert "no regression-gate" in plan_start(models, lc)["reason"]


def test_prior_promoted_seed_the_archive_and_are_not_promoted_again(tmp_path):
    from soccersim.selfplay.qd_archive import Archive, seed_archive
    from soccersim.selfplay.runs import prior_promoted

    toks, d = random_walk(5)
    d["id"] = "gen_old"
    d["provenance"] = {"run": 1, "archive_cell": {"band": "final_third", "lane": "center", "tempo": "fast",
                                                  "passes": 1, "objective": "score"},
                       "metrics": {"per_opponent": {"high_press": {"mean_reward": 0.02, "n": 3}}}}
    root = tmp_path / "promoted"
    (root / "run_1").mkdir(parents=True)
    import yaml

    (root / "run_1" / "gen_old.yaml").write_text(yaml.safe_dump(d))
    assert [p.id for p in prior_promoted(before_run=2, root=root)] == ["gen_old"]
    assert prior_promoted(before_run=1, root=root) == []
    a = Archive(min_evals=2)
    assert seed_archive(a, prior_promoted(root=root)) == []
    cell = next(iter(a.cells().values()))
    assert cell["elite"] == "gen_old" and a.plays["gen_old"]["prior_run"] == 1
    # A new play in the same niche must beat the carried-in elite to take the niche.
    new = dict(d, id="gen_new")
    desc = a.plays["gen_old"]["desc"]
    a.add(new, desc, 0.01, "x")
    a.add(new, desc, 0.01, "y")
    assert next(iter(a.cells().values()))["elite"] == "gen_old"
    a.add(new, desc, 0.09, "z")
    assert next(iter(a.cells().values()))["elite"] == "gen_new"
    # From a run with a different opponent pool, the old evaluations are dropped and the play
    # is returned for re-evaluation against the current pool.
    b = Archive(min_evals=2)
    assert seed_archive(b, prior_promoted(root=root), keep_evals_from={2, 3}) == ["gen_old"]
    assert b.plays["gen_old"]["evals"] == [] and b.plays["gen_old"]["prior_run"] == 1
    assert seed_archive(Archive(2), prior_promoted(root=root), keep_evals_from={1}) == []


def test_mutants_of_promoted_plays_record_their_lineage():
    toks, d = random_walk(9)
    d["id"] = "gen_parent"
    d["provenance"] = {"run": 2}
    parent = parse_play(d)
    rng = np.random.default_rng(1)
    m = next(x for x in (mutate(parent, rng) for _ in range(50)) if x is not None)
    assert m.provenance["parent"] == "gen_parent" and m.provenance["parent_run"] == 2


def test_pool_v2_styles_are_valid_and_two_are_held_out():
    from soccersim.config import load_config
    from soccersim.schema import load_library
    from soccersim.selfplay.policies import check_styles, style_spec

    lc = load_config("league")
    check_styles(lc, load_library())
    assert len(lc["scripted_styles"]) == 7 and sorted(lc["held_out_styles"]) == ["possession", "wing_play"]
    assert style_spec("chaotic", lc)["temperature"] > style_spec("high_press", lc)["temperature"]
    # Styles differ in what they do, never in formation (D-045).
    assert all(set(st) <= {"favour", "temperature"} for st in lc["scripted_styles"].values())
    bad = {**lc, "scripted_styles": {**lc["scripted_styles"], "x": {"favour": {"no_such_play": 0.1}}}}
    with pytest.raises(ValueError, match="no_such_play"):
        check_styles(bad, load_library())
    with pytest.raises(ValueError, match="nothing left"):
        check_styles({**lc, "held_out_styles": list(lc["scripted_styles"])}, load_library())


def test_held_out_styles_never_appear_in_training_data():
    from soccersim.config import load_config
    from soccersim.selfplay.runner import heldout_reference_jobs, phase_a_jobs

    held = set(load_config("league")["held_out_styles"])
    teams = {j[side]["id"] for j in phase_a_jobs(400, seed=3) for side in ("home", "away")}
    assert not teams & held and len(teams) == 1 + 7 - len(held)
    forms = {j["scenario"]["home_formation"] for j in phase_a_jobs(60, seed=3)}
    assert len(forms) > 1  # formations stay random for every team
    ref = heldout_reference_jobs(20)
    assert {j[s]["id"] for j in ref for s in ("home", "away")} == held | {"library"}


def test_forced_evaluations_randomise_formations():
    from soccersim.config import load_config
    from soccersim.generator.train import forced_scenario

    lc = load_config("league")
    pairs = {(forced_scenario("mid_progression", 0, k, lc).home_formation,
              forced_scenario("mid_progression", 0, k, lc).away_formation) for k in range(30)}
    assert len(pairs) > 3
    assert forced_scenario("mid_progression", 0, 5, lc) == forced_scenario("mid_progression", 0, 5, lc)
    old = forced_scenario("mid_progression", 0, 5, {**lc, "randomise_eval_formations": False})
    assert (old.home_formation, old.away_formation) == ("4-3-3", "4-3-3")


def test_base_models_must_match_the_opponent_pool(tmp_path):
    import json

    from soccersim.config import load_config
    from soccersim.selfplay.runs import check_base_models, pool_definition, pool_fingerprint

    lc = load_config("league")
    with pytest.raises(RuntimeError, match="predates pool versioning"):
        check_base_models(tmp_path, lc)  # pool v2 needs models trained for it
    v1 = {k: v for k, v in lc.items() if k not in ("pool_version", "randomise_eval_formations", "formations")}
    check_base_models(tmp_path, v1)  # legacy models are fine for a legacy (v1) pool
    assert pool_definition(v1) != pool_definition(lc)
    meta = {"critic_pool_fingerprint": pool_fingerprint(lc), "generator_pool_fingerprint": "something_else"}
    (tmp_path / "meta.json").write_text(json.dumps(meta))
    with pytest.raises(RuntimeError, match="generator"):
        check_base_models(tmp_path, lc)
    meta["generator_pool_fingerprint"] = pool_fingerprint(lc)
    (tmp_path / "meta.json").write_text(json.dumps(meta))
    check_base_models(tmp_path, lc)


def test_promoted_plays_join_the_library_in_place(tmp_path):
    import shutil

    from soccersim.config import PLAYS_DIR
    from soccersim.selfplay.runs import library_fingerprint

    hand = load_library(promoted_runs=())
    assert all(not (p.provenance or {}).get("adopted_into_library") for p in hand.values())
    # A copy of the plays tree: promoted plays are read from generated_and_promoted/run_N/.
    shutil.copytree(PLAYS_DIR, tmp_path / "plays")
    root = tmp_path / "plays"
    assert set(load_library(root)) == set(hand)  # an explicit root loads no promoted runs by default
    runs = sorted(int(d.name[4:]) for d in (root / "generated_and_promoted").glob("run_*") if d.is_dir())
    if not runs:
        pytest.skip("no promoted plays in this checkout")
    lib = load_library(root, promoted_runs=runs[:1])
    adopted = [p for p in lib.values() if (p.provenance or {}).get("adopted_into_library")]
    assert adopted and all(p.source == "library" and p.provenance["run"] == runs[0] for p in adopted)
    assert set(hand) < set(lib)
    assert library_fingerprint(lib) != library_fingerprint(hand)
    # The files themselves never move.
    assert list((root / "generated_and_promoted" / f"run_{runs[0]}").glob("*.yaml"))


def test_gap_categories():
    from soccersim.viz.training_report import gap_category

    fb = {"recycle_possession"}
    rec = {"play_id": "recycle_possession", "source": "library", "feasible": True, "score": 0.01}
    good = {"play_id": "switch_of_play", "source": "library", "feasible": True, "score": 0.05}
    weak = {**good, "score": 0.01}
    off = {**good, "feasible": False, "score": None}
    gen = {"play_id": "gen_x", "source": "generated", "feasible": True, "score": 0.09}
    assert gap_category([rec, good], fb, 0.03) == "real_play"
    assert gap_category([rec, weak], fb, 0.03) == "weak_fit"
    assert gap_category([rec, off, gen], fb, 0.03) == "only_circulation"  # generated plays do not count
    assert gap_category([{**rec, "feasible": False}], fb, 0.03) == "nothing_fits"
