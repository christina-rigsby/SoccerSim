"""Role assignment by the Hungarian algorithm (spec §9.3).

``cost = w_hint * hint_rank_cost + w_pref * (1 - prefers-weighted capability)
       + w_dist * travel_time_to_role_start + w_fatigue * (1 - stamina)``

Ineligible pairs cost ``1e6``; any ``1e6`` in the optimal solution makes the play
infeasible.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import linear_sum_assignment

from ..dashboard.team_state import TeamView
from ..schema.models import Play, Role
from ..sim.state import CAP_INDEX


@dataclass
class Assignment:
    feasible: bool
    binding: dict[str, list[int]] = field(default_factory=dict)
    total_cost: float = 0.0
    normalized_cost: float = 0.0
    hint_cost: float = 0.0          # mean hint-rank cost (tactical fit)
    pref_gap: float = 0.0           # mean (1 - prefers-weighted capability)
    fatigue: float = 0.0            # mean (1 - stamina) of bound players
    reason: str = ""


def hint_cost(hint: str, hints: list[str]) -> float:
    if not hints:
        return 0.5
    if hint in hints:
        return hints.index(hint) / len(hints)
    return 1.0


def pref_gap(view: TeamView, player: int, role: Role) -> float:
    if not role.prefers:
        return 0.0
    w = np.array(list(role.prefers.values()), dtype=float)
    c = np.array([view.state.caps[player, CAP_INDEX[k]] for k in role.prefers])
    return float(1.0 - np.dot(w, c) / max(w.sum(), 1e-9))


def role_start(view: TeamView, role: Role, side: float) -> np.ndarray | None:
    """Where a role "starts": the current position of our player best matching its first hint."""
    if role.starts_with_ball:
        return view.ball
    if not role.hints:
        return None
    for h in role.hints:
        for p in view.us:
            if view.hint_of(int(p), side) == h:
                return view.pos[int(p)]
    return None


def assign(play: Play, view: TeamView, side: float, cfg: dict) -> Assignment:
    ac = cfg["assignment"]
    inf = ac["infeasible_cost"]
    players = [int(p) for p in view.us]
    slots: list[Role] = []
    for r in play.roles:
        slots.extend([r] * r.slots)
    if len(slots) > len(players):
        return Assignment(False, reason="more role slots than players")
    holder = view.holder
    ball_role = play.ball_role
    if ball_role is not None and holder < 0:
        return Assignment(False, reason="ball role but we do not hold the ball")

    n, m = len(players), len(slots)
    cost = np.zeros((n, m))
    hc = np.zeros((n, m))
    pg = np.zeros((n, m))
    starts = {r.id: role_start(view, r, side) for r in play.roles}
    hints = {p: view.hint_of(p, side) for p in players}
    for i, p in enumerate(players):
        is_gk = view.state.kinds[p] == "GK"
        fatigue = 1.0 - float(view.state.stamina[p])
        for j, r in enumerate(slots):
            if r.starts_with_ball:
                if p != holder:
                    cost[i, j] = inf
                    continue
            elif ball_role is not None and p == holder:
                cost[i, j] = inf
                continue
            # Keepers only fill roles that list GK; keeper-only roles need the keeper.
            if (is_gk and "GK" not in r.hints) or (not is_gk and r.hints == ["GK"]):
                cost[i, j] = inf
                continue
            if any(view.state.caps[p, CAP_INDEX[k]] < v for k, v in r.requires.items()):
                cost[i, j] = inf
                continue
            h = hint_cost(hints[p], r.hints)
            g = pref_gap(view, p, r)
            start = starts[r.id]
            travel = 0.0 if start is None else float(np.hypot(*(view.pos[p] - start))) / ac["travel_speed"]
            hc[i, j], pg[i, j] = h, g
            cost[i, j] = ac["w_hint"] * h + ac["w_pref"] * g + ac["w_dist"] * travel + ac["w_fatigue"] * fatigue

    rows, cols = linear_sum_assignment(cost)
    chosen = cost[rows, cols]
    if np.any(chosen >= inf):
        bad = slots[int(cols[np.argmax(chosen)])].id
        return Assignment(False, reason=f"no eligible player for role {bad}")
    binding: dict[str, list[int]] = {r.id: [] for r in play.roles}
    for i, j in zip(rows, cols, strict=True):
        binding[slots[j].id].append(players[i])
    bound = [players[i] for i in rows]
    scale = ac["w_hint"] + ac["w_pref"] + ac["w_fatigue"] + ac["w_dist"] * 4.0
    return Assignment(
        True, binding, float(chosen.sum()), float(chosen.mean() / scale),
        float(hc[rows, cols].mean()), float(pg[rows, cols].mean()),
        float(np.mean(1.0 - view.state.stamina[bound])),
    )
