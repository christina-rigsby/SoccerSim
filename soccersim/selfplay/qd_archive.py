"""MAP-Elites archive of generated plays (spec §11 quality-diversity archive).

Descriptors: start band x start lane x tempo x number of passes x objective. Each cell
keeps the play with the best mean EPV delta among those with at least ``min_evals``
evaluations; plays below that are tracked as contenders.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from ..dashboard.zones import zone_of

PASS_TYPES = ("pass", "cross", "cutback", "clear", "distribute")


def n_passes(play: dict) -> int:
    n = 0
    for s in play["steps"]:
        acts = list(s.get("actions") or [])
        if s.get("choose"):
            acts = list(s["choose"][0]["actions"])  # the first branch is the play's intent
        n += sum(a["type"] in PASS_TYPES for a in acts)
    return min(n, 3)


def descriptor(play: dict, state: dict | None, side: float | None) -> tuple[str, str, str, int, str]:
    if state:
        ball = np.asarray(state["ball"], dtype=float)
        z = zone_of(ball, float(side or 1.0))
    else:
        z = "mid_opp.center"
    band, lane = z.split(".")
    return band, lane, play["soft_hints"]["tempo"], n_passes(play), play["objective"]


def cell_key(desc) -> str:
    return "|".join(map(str, desc))


class Archive:
    def __init__(self, min_evals: int = 50) -> None:
        self.min_evals = min_evals
        self.plays: dict[str, dict[str, Any]] = {}

    def add(self, play: dict, desc, reward: float, opponent: str, source: str = "selfplay") -> None:
        pid = play["id"]
        entry = self.plays.setdefault(pid, {"play": play, "cell": cell_key(desc), "desc": list(desc), "evals": []})
        entry["evals"].append([float(reward), opponent, source])

    def stats(self, pid: str) -> dict[str, float]:
        ev = self.plays[pid]["evals"]
        r = np.array([e[0] for e in ev], dtype=float)
        return {"n": len(r), "mean": float(r.mean()) if len(r) else 0.0}

    def cells(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for pid, e in self.plays.items():
            st = self.stats(pid)
            c = out.setdefault(e["cell"], {"desc": e["desc"], "plays": 0, "elite": None, "elite_mean": None,
                                           "best_contender": None, "best_contender_mean": None})
            c["plays"] += 1
            if st["n"] >= self.min_evals and (c["elite_mean"] is None or st["mean"] > c["elite_mean"]):
                c["elite"], c["elite_mean"], c["elite_n"] = pid, st["mean"], st["n"]
            if c["best_contender_mean"] is None or st["mean"] > c["best_contender_mean"]:
                c["best_contender"], c["best_contender_mean"] = pid, st["mean"]
        return out

    def elites(self) -> list[str]:
        return [c["elite"] for c in self.cells().values() if c["elite"]]

    def coverage(self) -> dict[str, int]:
        cells = self.cells()
        return {"cells": len(cells), "elite_cells": sum(1 for c in cells.values() if c["elite"]),
                "plays": len(self.plays)}

    def under_evaluated(self, k: int) -> list[str]:
        """Most promising contenders that still need evaluations to become elites."""
        cand = []
        for c in self.cells().values():
            pid = c["best_contender"]
            if pid and self.stats(pid)["n"] < self.min_evals:
                cand.append((c["best_contender_mean"], pid))
        return [pid for _, pid in sorted(cand, reverse=True)[:k]]

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps({"min_evals": self.min_evals, "plays": self.plays}))

    @classmethod
    def load(cls, path: str | Path, min_evals: int | None = None) -> Archive:
        p = Path(path)
        if not p.exists():
            return cls(min_evals or 50)
        data = json.loads(p.read_text())
        a = cls(min_evals or data["min_evals"])
        a.plays = data["plays"]
        return a
