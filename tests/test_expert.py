"""Expert iteration wiring (soccersim/selfplay/expert.py); training itself is exercised by scripts/expert.py."""

import pytest

from soccersim.selfplay.evaluate import team_spec
from soccersim.selfplay.expert import TRAIN_SEED, expert_spec, search_jobs
from soccersim.selfplay.objectives import situations


def test_search_plays_for_the_objective_and_records_situations(tmp_path):
    jobs = search_jobs("win_back_8", 4, 0, tmp_path)
    for j in jobs:
        assert j["me"]["objective"] == "win_back_8" and j["me"]["record_state"]
        assert j["scenario"]["attacking_team"] == 1 - j["side"]  # they have the ball
    # Training situations differ from the evaluation's.
    assert situations("win_back_8", 4, TRAIN_SEED) != situations("win_back_8", 4)


def test_later_iterations_search_on_the_previous_network(tmp_path):
    (tmp_path / "expert" / "keep_30" / "iter_0").mkdir(parents=True)
    (tmp_path / "expert" / "keep_30" / "iter_0" / "critic.pt").write_bytes(b"")
    j = search_jobs("keep_30", 1, 1, tmp_path)[0]
    assert j["me"]["base"]["checkpoint"].endswith("iter_0")


def test_expert_team_names(tmp_path):
    with pytest.raises(ValueError):
        expert_spec("keep_30", None, tmp_path)
    (tmp_path / "expert" / "keep_30" / "iter_2").mkdir(parents=True)
    (tmp_path / "expert" / "keep_30" / "iter_2" / "critic.pt").write_bytes(b"")
    assert team_spec("expert@keep_30", tmp_path)["checkpoint"].endswith("iter_2")
    assert team_spec("expert0@keep_30", tmp_path)["checkpoint"].endswith("iter_0")
