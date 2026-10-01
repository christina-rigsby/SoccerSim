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


def seed_archive(archive: Archive, plays, keep_evals_from: set[int] | None = None) -> list[str]:
    """Option 3: seed a new run's archive with earlier runs' promoted plays.

    Each keeps the evaluations recorded in its provenance (mean and count per opponent), so a
    new play only takes over a niche by beating it there. Seeded plays are marked with
    ``prior_run`` and are never promoted again.

    ``keep_evals_from``: runs whose evaluations are still comparable (same opponent pool).
    Plays from other runs are seeded without evaluations — their old numbers were earned
    against different opponents — and the returned ids must be re-evaluated before training.
    ``None`` keeps every play's evaluations.
    """
    pending = []
    for play in plays:
        prov = play.provenance or {}
        cell = prov.get("archive_cell")
        if not cell:
            continue
        desc = [cell["band"], cell["lane"], cell["tempo"], int(cell["passes"]), cell["objective"]]
        d = play.model_dump(mode="json", exclude_none=True)
        per_opp = (prov.get("metrics") or {}).get("per_opponent") or {}
        evals: list = []
        if keep_evals_from is not None and prov.get("run") not in keep_evals_from:
            archive.plays[play.id] = {"play": d, "cell": cell_key(desc), "desc": desc, "evals": [],
                                      "prior_run": prov.get("run")}
            pending.append(play.id)
            continue
        for opp, m in per_opp.items():
            if m.get("mean_reward") is None:
                continue
            evals += [[float(m["mean_reward"]), opp, f"run{prov.get('run')}"]] * int(max(1, m.get("n", 1)))
        if not evals:
            mean = float((prov.get("metrics") or {}).get("overall", {}).get("mean", 0.0))
            evals = [[mean, "unknown", f"run{prov.get('run')}"]] * archive.min_evals
        archive.plays[play.id] = {"play": d, "cell": cell_key(desc), "desc": desc, "evals": evals,
                                  "prior_run": prov.get("run")}
    return pending
