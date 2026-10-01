"""M0 acceptance: all starter plays validate; every invalid fixture fails clearly (spec §6.13)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from soccersim.schema import PlayValidationError, load_library, load_play_file, parse_play, play_to_dict

FIXTURES = Path(__file__).parent / "fixtures" / "invalid_plays"
INVALID = sorted(FIXTURES.glob("*.yaml"))

STARTERS = {
    "wide_overlap_cross", "third_man_combination", "switch_of_play", "through_ball_behind_high_line",
    "one_two_wall_pass", "build_out_short_goal_kick", "direct_counterattack", "recycle_possession",
    "high_press_sideline_trap", "mid_block_compact", "low_block_box_protection", "counterpress_five_seconds",
}


def test_all_starter_plays_validate():
    lib = load_library()
    assert set(lib) == STARTERS
    assert sum(p.fallback for p in lib.values()) == 1
    assert sum(p.phase in ("out_of_possession", "transition_defense") for p in lib.values()) == 4


def test_round_trip_is_stable():
    for play in load_library().values():
        again = parse_play(play_to_dict(play))
        assert play_to_dict(again) == play_to_dict(play)


def _expected(path: Path) -> str:
    first = path.read_text().splitlines()[0]
    assert first.startswith("# expect:"), path
    return first.split(":", 1)[1].strip()


@pytest.mark.parametrize("path", INVALID, ids=[p.stem for p in INVALID])
def test_invalid_fixture_fails_with_clear_error(path):
    with pytest.raises(PlayValidationError) as exc:
        load_play_file(path)
    assert _expected(path) in str(exc.value), str(exc.value)
    assert str(path) in str(exc.value)


def test_required_fixtures_present():
    names = {p.stem for p in INVALID}
    for needed in ("both_actions_and_choose", "always_as_mapping", "undefined_role", "unknown_zone",
                   "goto_missing_step", "two_ball_roles"):
        assert needed in names


def test_timed_cycle_is_allowed():
    data = yaml.safe_load((FIXTURES / "untimed_cycle.yaml").read_text())
    for step in data["steps"]:
        step["timeout_s"] = 2
    parse_play(data)


def test_unknown_top_level_key_rejected():
    data = play_to_dict(load_library()["recycle_possession"])
    data["tirggers"] = "always"
    with pytest.raises(PlayValidationError, match="tirggers"):
        parse_play(data)
