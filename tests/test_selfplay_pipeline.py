"""M6 + the whole Module 3 pipeline end to end at "smoke" scale.

The logging test is fast. The full pipeline test (Phase A -> critic -> BC + mutation ->
league -> promotion -> report) takes a few minutes, so it is marked ``slow``:
``pytest -m slow``.
"""

from __future__ import annotations

import json

import pytest

from soccersim.eval.reports import fit_xt_from_runs, summarize
from soccersim.selfplay.logging import load_table
from soccersim.selfplay.runner import phase_a_jobs, run_jobs


@pytest.fixture(scope="module")
def phase_a(tmp_path_factory):
    root = tmp_path_factory.mktemp("selfplay")
    out = run_jobs(phase_a_jobs(10, seed=3, tracking_every=5, run_id="t"), root, "t", workers=2, progress_every=0)
    return root, out


def test_phase_a_logs_parquet_rows(phase_a):
    root, out = phase_a
    t = load_table(root)
    assert t.num_rows == out["decisions"] > 50
    row = t.slice(0, 1).to_pylist()[0]
    for col in ("episode_id", "t", "team", "reason", "state", "candidates", "chosen", "opp_active_play", "events",
                "end_reason", "duration_s", "epv_start", "epv_end", "reward", "sim_config_hash", "opponent_id"):
        assert col in row
    state = json.loads(row["state"])
    assert len(state["pos"]) == 22 and "lines" in state
    assert json.loads(row["candidates"])
    eps = load_table(root, "episodes")
    assert eps.num_rows == 10
    assert list((root / "run=t" / "tracking").glob("*.json.gz"))


def test_summary_and_fitted_xt(phase_a, tmp_path):
    root, _ = phase_a
    s = summarize(root)
    assert s["episodes"] == 10 and abs(sum(p["share"] for p in s["plays"]) - 1.0) < 1e-6
    info = fit_xt_from_runs(root, tmp_path / "xt.json")
    assert info["moves"] > 0 and (tmp_path / "xt.json").exists()


@pytest.mark.slow
def test_full_pipeline_smoke(phase_a, tmp_path):
    pytest.importorskip("torch")
    from soccersim.generator.train import pretrain_generator, train_critic_and_response
    from soccersim.selfplay.league import League
    from soccersim.selfplay.promote import promote_elites
    from soccersim.viz.training_report import build_report

    root, _ = phase_a
    models = tmp_path / "models"
    crit = train_critic_and_response(root, models, profile="smoke")
    assert "mse" in crit["critic"] and (models / "critic.pt").exists()
    gen = pretrain_generator(root, models, profile="smoke", workers=2)
    assert gen["validity"]["validity"] >= 0.99
    promoted = tmp_path / "promoted"
    lg = League(models, tmp_path / "league_data", profile="smoke", promoted_root=promoted)
    assert lg.run == 1 and lg.run_info["continued_from"] is None
    rec = lg.run_update(workers=2)
    assert rec["update"] == 1 and rec["validity"] >= 0.99
    lg.evaluate(n=1, workers=2)
    lg.lcfg.update(gate_games=1, gate_tolerance_abs=10.0)   # smoke scale: let the gate pass
    assert lg.regression_gate(workers=2)["passed"]
    promo = promote_elites(models, root, promoted, profile="smoke", workers=2, rollouts=1)
    assert promo["run"] == 1
    for pid in promo["promoted_ids"]:
        text = (promoted / "run_1" / f"{pid}.yaml").read_text()
        assert "pending_human_review" in text

    # Run 2: earlier promoted plays are mutated and imitated (options 1-2), seed the archive
    # (option 3), and the generator continues from run 1 because the pool is unchanged and
    # run 1 passed its gate (option 4).
    gen2 = pretrain_generator(root, models, profile="smoke", workers=2, promoted_root=promoted)
    assert gen2["prior_promoted"]["plays"] == len(promo["promoted_ids"])
    lg2 = League(models, tmp_path / "league_data", profile="smoke", promoted_root=promoted)
    assert lg2.run == 2 and lg2.run_info["continued_from"] == 1
    assert "run1@final" in lg2.snapshots
    if promo["promoted_ids"]:
        assert lg2.run_info["seeded_from_runs"] == [1]
        assert all(lg2.archive.plays[p]["prior_run"] == 1 for p in promo["promoted_ids"])
    out = build_report(models, root, tmp_path / "report.html")
    html = out.read_text()
    assert "Self-Play Lab" in html and "How each run builds on the last" in html


def test_parquet_log_resumes_without_overwriting(tmp_path):
    from soccersim.selfplay.logging import ParquetLog, load_table

    log = ParquetLog(tmp_path, "r")
    log.add([{"episode_id": "e0", "t": 0.0, "team": 0}], {"episode_id": "e0"})
    log.flush()
    # A restarted process opens the same run and must append, not overwrite part 0.
    log2 = ParquetLog(tmp_path, "r")
    assert log2.part == 1
    log2.add([{"episode_id": "e1", "t": 0.0, "team": 0}], {"episode_id": "e1"})
    log2.flush()
    eps = sorted(load_table(tmp_path, "episodes", ["episode_id"]).column("episode_id").to_pylist())
    assert eps == ["e0", "e1"]
    assert not list(tmp_path.rglob("*.tmp"))


def test_successful_generated_plays_are_clipped():
    import yaml

    from soccersim.config import PLAYS_DIR
    from soccersim.schema import load_library, parse_play
    from soccersim.selfplay.worker import SUCCESS_MIN_REWARD, generated_success_clips
    from soccersim.sim.play_scenarios import run_play
    from soccersim.sim.scenarios import Scenario

    files = sorted((PLAYS_DIR / "generated_and_promoted").glob("run_*/*.yaml"))
    if not files:
        pytest.skip("no promoted plays in this checkout")
    data = yaml.safe_load(files[0].read_text())
    data["source"] = "generated"
    play = parse_play(data)
    lib = load_library(promoted_runs=())
    run = None
    for seed in range(40):
        r = run_play(lib, play.id, seed, Scenario(type="final_third_attack"), extra=play, max_time_s=15)
        if r.forced_record(play.id) is not None:
            run = r
            break
    assert run is not None
    rec = run.forced_record(play.id)
    job = {"episode_id": "t", "home": {"id": "main"}, "away": {"id": "high_press"}}
    rec["reward"] = 0.0
    rec["end_reason"] = "abort"
    assert generated_success_clips(run.result, job) == []
    rec["reward"] = SUCCESS_MIN_REWARD * 2
    (clip,) = generated_success_clips(run.result, job)
    assert clip["play_id"] == play.id and clip["player"] == "main" and clip["opponent"] == "high_press"
    assert clip["play_yaml"] and clip["replay"]["frames"]
    assert all(rec["t_start"] - 1.01 <= f["t"] <= rec["t_end"] + 2.01 for f in clip["replay"]["frames"])
