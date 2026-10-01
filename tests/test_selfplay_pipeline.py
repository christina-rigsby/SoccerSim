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
    lg = League(models, tmp_path / "league_data", profile="smoke")
    rec = lg.run_update(workers=2)
    assert rec["update"] == 1 and rec["validity"] >= 0.99
    lg.evaluate(n=1, workers=2)
    promo = promote_elites(models, root, tmp_path / "promoted", profile="smoke", workers=2, rollouts=1)
    for pid in promo["promoted_ids"]:
        text = (tmp_path / "promoted" / f"run_{promo['run']}" / f"{pid}.yaml").read_text()
        assert "pending_human_review" in text
    out = build_report(models, root, tmp_path / "report.html")
    assert "Self-Play Lab" in out.read_text()
