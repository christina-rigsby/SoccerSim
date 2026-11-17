"""An interrupted evaluation resumes from its partial file instead of replaying finished games."""

from __future__ import annotations

import json

from soccersim.selfplay import evaluate


def test_finished_games_are_not_played_again(tmp_path, monkeypatch):
    played: list[str] = []

    def fake_run_jobs(jobs, out_root, workers=0, on_result=None, progress_every=0):
        for j in jobs:
            played.append(j["episode_id"])
            on_result({"episode": {"episode_id": j["episode_id"]}, "events": []})

    monkeypatch.setattr("soccersim.selfplay.runner.run_jobs", fake_run_jobs)
    partial = tmp_path / "games.partial.jsonl"
    jobs = evaluate.build_jobs(["library"], ["high_press"], 2)
    first = jobs[0]
    partial.write_text(json.dumps({**first["eval"], "episode_id": first["episode_id"], "gd": 0, "xgd": 0.0, "sd": 0,
                                   "gf": 0, "ga": 0, "xgf": 0.0, "xga": 0.0}) + "\n")
    ev = evaluate.run_evaluation(["library"], ["high_press"], 2, workers=1, partial=partial)
    assert first["episode_id"] not in played and len(played) == len(jobs) - 1
    assert len(ev["games"]) == len(jobs)
    assert len(partial.read_text().splitlines()) == len(jobs)
