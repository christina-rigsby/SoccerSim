"""Self-contained interactive HTML replay viewer (spec §13).

``export_replay_html`` embeds one or more episodes (frames, play records, decisions,
events) as JSON and renders them on a canvas: players with role labels, the ball, each
player's current target, each team's active play and step, a play timeline per team
(generated plays highlighted), and a decision inspector listing every candidate Module 2
scored at the last decision — including whether the library left a gap and the
generator was consulted.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..sim.env import EpisodeResult

_TEMPLATE = Path(__file__).with_name("replay_template.html")


SHORT_REASONS = {"ball role but we do not hold the ball": "ball not ours", "triggers": "triggers fail",
                 "more role slots than players": "too many roles"}


def _short(reason: str) -> str:
    if reason.startswith("no eligible player for role"):
        return "no player for " + reason.rsplit(" ", 1)[-1]
    if reason.startswith("hard_constraints"):
        return "hard constraint"
    return SHORT_REASONS.get(reason, reason)


def episode_payload(res: EpisodeResult | dict[str, Any], title: str = "", stride: int = 1) -> dict[str, Any]:
    r = res if isinstance(res, dict) else res.__dict__
    frames = r["frames"][::stride]
    plays = []
    for p in r["plays"]:
        q = {k: p.get(k) for k in ("play_id", "source", "team", "t_start", "t_end", "end_reason", "steps_visited",
                                   "binding", "epv_start", "epv_end", "reward")}
        if p.get("play_yaml"):
            q["play_yaml"] = p["play_yaml"]
        plays.append(q)
    decisions = []
    for d in r["decisions"]:
        cands = sorted(d.get("candidates", []), key=lambda c: -(c["score"] if c["score"] is not None else -9))
        decisions.append({
            "t": d["t"], "team": d["team"], "reason": d["reason"], "chosen": d.get("chosen"),
            "kept": d.get("kept_active"), "gen": d.get("generator_used"), "gap": d.get("library_gap"),
            "c": [[c["play_id"], c["source"], c["feasible"], _short(c["reason"]), c["score"]] for c in cands],
        })
    return {
        "title": title or f"seed {r['seed']} · {r['scenario'].get('type', '')}",
        "scenario": r["scenario"], "score": r["score"], "end": r["end_cause"], "duration": r["duration_s"],
        "frames": frames, "plays": plays, "decisions": decisions,
        "events": [e for e in r["events"] if e["type"] in (
            "shot_taken", "goal", "possession_won", "pass_intercepted", "foul_won", "offside")],
    }


def render_replay_html(episodes: list[dict[str, Any]], heading: str = "Self-play replay",
                       fragment: bool = False) -> str:
    """HTML for a list of :func:`episode_payload` dicts.

    ``fragment=True`` omits the document skeleton (for publishing as an artifact).
    """
    tpl = _TEMPLATE.read_text()
    data = json.dumps({"heading": heading, "episodes": episodes}, separators=(",", ":"))
    body = tpl.replace("__DATA__", data.replace("</", "<\\/")).replace("__HEADING__", heading)
    if fragment:
        return body
    return f'<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n' \
           f'<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n' \
           f'</head>\n<body>\n{body}\n</body>\n</html>\n'


def export_replay_html(episodes: list[EpisodeResult | dict], path: str | Path, titles: list[str] | None = None,
                       heading: str = "Self-play replay", stride: int = 1, fragment: bool = False) -> Path:
    titles = titles or [""] * len(episodes)
    payload = [episode_payload(e, t, stride) for e, t in zip(episodes, titles, strict=True)]
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_replay_html(payload, heading, fragment))
    return path
