"""Play scoring in EPV units (spec §9.4).

``score = graph_path_value(objective, strategy | game_state)
        - sum(soft_penalties(risk, fatigue, tactical_fit, chain_depth, execution_confidence))
        - lambda_assign * normalized_assignment_cost
        + critic_value(state, play)
        + style_bonus``  (scripted league opponents only)
"""

from __future__ import annotations

from collections.abc import Callable

from ..dashboard.team_state import TeamView
from ..schema.models import Play
from .assignment import Assignment
from .graph import graph_path_value

CriticFn = Callable[[TeamView, Play, dict], float]


def score_play(
    play: Play,
    view: TeamView,
    asg: Assignment,
    cfg: dict,
    critic: CriticFn | None = None,
    style_bonus: float = 0.0,
) -> tuple[float, dict[str, float]]:
    pen = cfg["penalties"]
    comp: dict[str, float] = {}
    comp["graph"] = graph_path_value(play, view.score_diff, view.minute, cfg)
    comp["risk"] = -pen["risk"] * play.soft_hints.risk
    comp["fatigue"] = -pen["fatigue"] * asg.fatigue
    comp["tactical_fit"] = -pen["tactical_fit"] * asg.hint_cost
    comp["chain_depth"] = -pen["chain_depth"] * play.soft_hints.chain_depth
    comp["execution_confidence"] = -pen["execution_confidence"] * asg.pref_gap
    comp["assignment"] = -cfg["lambda_assign"] * asg.normalized_cost
    comp["critic"] = 0.0
    if critic is not None and cfg.get("critic", {}).get("enabled", False):
        comp["critic"] = cfg["critic"].get("weight", 1.0) * float(critic(view, play, asg.binding))
    if style_bonus:
        comp["style"] = style_bonus
    return float(sum(comp.values())), {k: round(v, 5) for k, v in comp.items()}
