"""Play variants: candidate library changes tried by one team in evaluation."""

from __future__ import annotations

import numpy as np

from soccersim.schema import load_library
from soccersim.schema.loader import load_variant_library
from soccersim.selfplay.evaluate import team_spec
from soccersim.selfplay.policies import make_policy

LIB = load_library()


def test_a_variant_adds_replaces_and_removes_plays():
    v = load_variant_library("branchy+defensive_plus+prune_failing", LIB)
    assert {"delay_and_recover", "wide_double_up", "box_defence_cross", "press_build_up_central"} <= set(v)
    assert v["one_two_wall_pass"].version == 2 and LIB["one_two_wall_pass"].version == 1
    assert "gen_263419283b" in LIB and "gen_263419283b" not in v


def test_only_the_named_team_gets_the_variant():
    spec = team_spec("library+defensive_plus")
    assert spec["plays_variant"] == "defensive_plus"
    pol = make_policy(spec, LIB, np.random.default_rng(0))
    plain = make_policy(team_spec("library"), LIB, np.random.default_rng(0))
    assert "wide_double_up" in pol.library and "wide_double_up" not in plain.library
    assert "wide_double_up" not in LIB
