"""Play-level rewards (spec §12).

Per play, from instantiation to end::

    r = dEPV(end - start) + 1.0 * goal_scored - 1.0 * goal_conceded
        - c_loss * possession_lost_in_own_half + shot_xg * (xG of our shots - xG of theirs)

``possession_return`` adds the discounted rewards of the team's later plays in the same
possession, so a play that sets up a shot or a goal shares the credit; the critic and the
generator learn from it when ``rewards.target`` is ``possession_return`` (configs/training.yaml).

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
        elif et == "shot_taken" and rc.get("shot_xg", 0.0):
            # A shot counts by its quality (xG), so a good chance is credited even when missed;
            # an opponent's shot during the play counts against it.
            xg = float((ev.get("data") or {}).get("xg") or 0.0)
            r += rc["shot_xg"] * xg * (1.0 if ev.get("team") == team else -1.0)
    return float(r)


def possession_spells(seq: list[dict[str, Any]], phases: dict[str, str]) -> list[list[dict[str, Any]]]:
    """Split one team's plays (in time order) into possessions: a new spell starts when the team
    switches between having and not having the ball, or after a play in which a goal fell."""
    spells: list[list[dict[str, Any]]] = []
    prev_def = None
    for p in seq:
        is_def = phases.get(p["play_id"], "in_possession") in DEFENSIVE
        if not spells or is_def != prev_def:
            spells.append([])
        spells[-1].append(p)
        prev_def = is_def
        if any(ev["type"] in ("goal", "goal_conceded") for ev in p.get("events", [])):
            prev_def = None  # force a new spell for the next play
    return spells


def credit_cross_team_events(plays: list[dict[str, Any]]) -> int:
    """Give each team's play records the events the other side caused that its reward needs.

    A play only records events of its own team, and the scoring team's play usually ends when the
    shot is struck (``shot_taken`` success, or the ball leaving the carrier), before the goal
    registers. Then only the defending play, still running, sees the goal (as ``goal_conceded``)
    and the scorer is never credited. This adds, in place:

    - a ``goal`` to the scoring team's play that took the shot (else its latest play started
      before the goal), for every ``goal_conceded`` without a matching ``goal``;
    - the opponent's ``shot_taken`` to the defending play running at that moment, so the
      ``shot_xg`` term counts against it.

    Returns how many goals were credited this way.
    """
    credited = 0
    for team in (0, 1):
        own = sorted((p for p in plays if p["team"] == team), key=lambda p: p["t_start"])
        opp = [p for p in plays if p["team"] == 1 - team]
        have = {round(ev["t"], 2) for p in own for ev in p.get("events", []) if ev["type"] == "goal" and "t" in ev}
        for p in opp:
            for ev in list(p.get("events", [])):
                if ev["type"] == "goal_conceded" and "t" in ev and round(ev["t"], 2) not in have:
                    t = ev["t"]
                    before = [q for q in own if q["t_start"] <= t]
                    if not before:
                        continue
                    shooters = [q for q in before if any(e["type"] == "shot_taken" and e.get("team") == team
                                                         and e.get("t", t) <= t for e in q.get("events", []))]
                    q = shooters[-1] if shooters else before[-1]
                    q.setdefault("events", []).append({**ev, "type": "goal", "team": team,
                                                       "data": {"credited_after_play_end": True}})
                    have.add(round(t, 2))
                    credited += 1
        # Opponent shots against the defending play running at the time.
        for p in opp:
            for ev in p.get("events", []):
                if ev["type"] != "shot_taken" or ev.get("team") != 1 - team or "t" not in ev:
                    continue
                t = ev["t"]
                for q in own:
                    t_end = q.get("t_end") if q.get("t_end") is not None else q["t_start"]
                    if q["t_start"] <= t <= t_end and not any(
                            e["type"] == "shot_taken" and e.get("t") == t for e in q.get("events", [])):
                        q.setdefault("events", []).append(dict(ev))
                        break
    return credited


def assign_rewards(plays: list[dict[str, Any]], phases: dict[str, str], objectives: dict[str, str],
                   cfg: dict | None = None) -> None:
    """Fill ``reward``, discounted ``return`` and ``possession_return`` on every play record, in place."""
    cfg = cfg or load_config("training")
    rc = cfg["rewards"]
    credit_cross_team_events(plays)
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
        # Longer horizon: each play is also credited with what the rest of its team's
        # possession earned (discounted per play), up to the end of that possession.
        for spell in possession_spells(seq, phases):
            g = 0.0
            for p in reversed(spell):
                g = p["reward"] + gamma * g
                p["possession_return"] = round(g, 6)
