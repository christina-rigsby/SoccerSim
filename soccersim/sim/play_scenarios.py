"""Scenarios in which a given play's triggers hold (spec §6.13 execution tests).

Rather than hand-placing 22 players per play, each play maps to the scenario types
whose start states can satisfy its triggers, and :func:`find_play_scenario` runs short
episodes over seeds until the play is actually instantiated by Module 2's own trigger
check. The seeds found are pinned in ``tests/fixtures/play_scenarios.json`` so the tests
are deterministic; ``scripts/find_play_scenarios.py`` regenerates that file.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..ranking.selector import ForcedPolicy, RankingPolicy
from ..schema.models import Play
from .env import EpisodeResult, MatchEnv
from .scenarios import Scenario

#: play id -> (scenario types, which team attacks). The forced team is always team 0.
PLAY_SCENARIOS: dict[str, tuple[tuple[str, ...], int]] = {
    "wide_overlap_cross": (("final_third_attack", "mid_progression", "random_open_play"), 0),
    "third_man_combination": (("mid_progression", "random_open_play", "transition_win"), 0),
    "switch_of_play": (("mid_progression", "final_third_attack", "random_open_play"), 0),
    "through_ball_behind_high_line": (("mid_progression", "transition_win", "random_open_play"), 0),
    "one_two_wall_pass": (("final_third_attack", "random_open_play", "mid_progression"), 0),
    "build_out_short_goal_kick": (("build_up",), 0),
    "direct_counterattack": (("transition_win",), 0),
    "recycle_possession": (("mid_progression", "random_open_play"), 0),
    "high_press_sideline_trap": (("build_up", "mid_progression", "random_open_play"), 1),
    "mid_block_compact": (("mid_progression", "random_open_play"), 1),
    "low_block_box_protection": (("final_third_attack", "random_open_play"), 1),
    "counterpress_five_seconds": (("transition_loss",), 1),
}


@dataclass
class PlayRun:
    seed: int
    scenario: Scenario
    result: EpisodeResult

    def forced_record(self, play_id: str) -> dict | None:
        for p in self.result.plays:
            if p["team"] == 0 and p["play_id"] == play_id:
                return p
        return None


def run_play(library: dict[str, Play], play_id: str, seed: int, scenario: Scenario, max_time_s: float = 25.0,
             extra: Play | None = None, ignore_triggers: bool = False, env: MatchEnv | None = None,
             opponent_style: str | None = None) -> PlayRun:
    env = env or MatchEnv()
    env.reset(seed, scenario)
    forced = ForcedPolicy(library, play_id, extra=extra, ignore_triggers=ignore_triggers,
                          rng=np.random.default_rng(seed))
    style = None
    if opponent_style:
        from ..selfplay.policies import style_bonus

        style = style_bonus(opponent_style)
    other = RankingPolicy(library, rng=np.random.default_rng(seed + 1), style=style)
    res = env.run(forced, other, max_time_s=max_time_s, stop_on_turnover=False, stop_on_goal=True)
    return PlayRun(seed, scenario, res)


def find_play_scenario(library: dict[str, Play], play_id: str, max_seeds: int = 60,
                       max_time_s: float = 25.0) -> PlayRun | None:
    types, attacking = PLAY_SCENARIOS[play_id]
    env = MatchEnv()
    for seed in range(max_seeds):
        sc = Scenario(type=types[seed % len(types)], attacking_team=attacking)
        run = run_play(library, play_id, seed, sc, max_time_s, env=env)
        if run.forced_record(play_id) is not None:
            return run
    return None
