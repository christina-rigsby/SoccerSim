"""Play-level rewards (spec §12).

Per play, from instantiation to end::

    r = dEPV(end - start) + 1.0 * goal_scored - 1.0 * goal_conceded
        - c_loss * possession_lost_in_own_half

Out-of-possession plays use the same EPV (it is already from our side, so a fall in the
opponent's EPV is a rise in ours) plus a regain bonus. Returns are discounted across a
team's consecutive plays with gamma per play. Possession farming is guarded by capping
the reward that consecutive non-improving ``retain_possession`` plays can collect.
"""

from __future__ import annotations

from typing import Any

from ..config import load_config

DEFENSIVE = ("out_of_possession", "transition_defense")


def play_reward(rec: dict[str, Any], phase: str, cfg: dict | None = None) -> float:
    rc = (cfg or load_config("training"))["rewards"]
    team = rec["team"]
    epv0 = rec.get("epv_start") or 0.0
    epv1 = rec.get("epv_end") if rec.get("epv_end") is not None else epv0
    r = epv1 - epv0
    for ev in rec.get("events", []):
        et = ev["type"]
        if et == "goal" and ev.get("team") == team:
            r += rc["goal"]
        elif et == "goal_conceded" and ev.get("team") == team:
            r -= rc["goal"]
        elif et == "possession_lost" and ev.get("team") == team:
            x = ev["pos"][0] * (1 if team == 0 else -1)
            if x < 0:
                r -= rc["c_loss_own_half"]
        elif et == "possession_won" and ev.get("team") == team and phase in DEFENSIVE:
            r += rc["regain_bonus"]
    return float(r)


def assign_rewards(plays: list[dict[str, Any]], phases: dict[str, str], objectives: dict[str, str],
                   cfg: dict | None = None) -> None:
    """Fill ``reward`` and discounted ``return`` on every play record, in place."""
    cfg = cfg or load_config("training")
    rc = cfg["rewards"]
    gamma = rc["gamma_per_play"]
    for team in (0, 1):
        seq = sorted((p for p in plays if p["team"] == team), key=lambda p: p["t_start"])
        retain_sum = 0.0
        for p in seq:
            r = play_reward(p, phases.get(p["play_id"], "in_possession"), cfg)
            if objectives.get(p["play_id"]) == "retain_possession" and (p.get("epv_end") or 0) <= (p.get("epv_start")
                                                                                                or 0):
                room = max(rc["retain_cap"] - retain_sum, 0.0)
                if r > room:
                    r = room
                retain_sum += max(r, 0.0)
            else:
                retain_sum = 0.0
            p["reward"] = round(r, 6)
        g = 0.0
        for p in reversed(seq):
            g = p["reward"] + gamma * g
            p["return"] = round(g, 6)
