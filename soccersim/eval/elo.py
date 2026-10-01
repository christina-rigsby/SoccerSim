"""Elo ratings and a payoff matrix for the league (spec §11 Phase C)."""

from __future__ import annotations

from collections import defaultdict
from typing import Any


class Elo:
    def __init__(self, k: float = 24.0, initial: float = 1000.0) -> None:
        self.k = k
        self.initial = initial
        self.ratings: dict[str, float] = {}

    def get(self, pid: str) -> float:
        return self.ratings.setdefault(pid, self.initial)

    def expected(self, a: str, b: str) -> float:
        return 1.0 / (1.0 + 10 ** ((self.get(b) - self.get(a)) / 400.0))

    def update(self, a: str, b: str, score_a: float) -> None:
        ea = self.expected(a, b)
        self.ratings[a] = self.get(a) + self.k * (score_a - ea)
        self.ratings[b] = self.get(b) + self.k * ((1 - score_a) - (1 - ea))


class Payoff:
    """results[a][b] = {"w", "d", "l", "n", "reward"} from a's point of view."""

    def __init__(self) -> None:
        self.results: dict[str, dict[str, dict[str, float]]] = defaultdict(
            lambda: defaultdict(lambda: {"w": 0, "d": 0, "l": 0, "n": 0, "reward": 0.0}))

    def add(self, a: str, b: str, score_a: float, reward_a: float) -> None:
        for x, y, s, r in ((a, b, score_a, reward_a), (b, a, 1 - score_a, -reward_a)):
            c = self.results[x][y]
            c["n"] += 1
            c["reward"] += r
            c["w" if s > 0.5 else "l" if s < 0.5 else "d"] += 1

    def win_rate(self, a: str, b: str, prior: float = 0.5) -> float:
        c = self.results.get(a, {}).get(b)
        if not c or not c["n"]:
            return prior
        return (c["w"] + 0.5 * c["d"] + prior) / (c["n"] + 1)

    def to_json(self) -> dict[str, Any]:
        return {a: {b: dict(c) for b, c in row.items()} for a, row in self.results.items()}

    @classmethod
    def from_json(cls, data: dict) -> Payoff:
        p = cls()
        for a, row in data.items():
            for b, c in row.items():
                p.results[a][b] = dict(c)
        return p
