"""The objective -> strategy -> play weighted graph (spec §9.4 ``graph_path_value``).

Weights live in ``configs/ranking.yaml`` and are functions of game state: trailing late
raises ``create_chance``, leading late raises ``retain_possession``. Values are in EPV
units so they add directly to the critic and the penalties.
"""

from __future__ import annotations

from ..schema.models import Play


def _condition(when: dict, score_diff: int, minute: float) -> bool:
    ok = True
    if "score_diff_lt" in when:
        ok &= score_diff < when["score_diff_lt"]
    if "score_diff_gt" in when:
        ok &= score_diff > when["score_diff_gt"]
    if "minute_gt" in when:
        ok &= minute > when["minute_gt"]
    if "minute_lt" in when:
        ok &= minute < when["minute_lt"]
    return bool(ok)


def objective_weight(objective: str, score_diff: int, minute: float, cfg: dict) -> float:
    w = float(cfg["objective_value"].get(objective, 0.0))
    for mod in cfg.get("game_state_modifiers", []):
        if _condition(mod["when"], score_diff, minute):
            w *= float(mod["multiply"].get(objective, 1.0))
    return w


def graph_path_value(play: Play, score_diff: int, minute: float, cfg: dict) -> float:
    strategy = play.strategy if play.source == "library" or play.strategy in cfg["strategy_value"] else "generated"
    return objective_weight(play.objective, score_diff, minute, cfg) + float(
        cfg["strategy_value"].get(strategy, 0.0)
    )


def graph_edges(library: dict[str, Play], cfg: dict) -> list[tuple[str, str, float]]:
    """(src, dst, weight) edges of the static graph, for visualisation."""
    edges = []
    for play in library.values():
        edges.append((f"obj:{play.objective}", f"strat:{play.strategy}", cfg["objective_value"].get(play.objective, 0)))
        edges.append((f"strat:{play.strategy}", f"play:{play.id}", cfg["strategy_value"].get(play.strategy, 0)))
    return sorted(set(edges))
