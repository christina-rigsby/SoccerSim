"""Prioritised fictitious self-play (spec §11 Phase C): sample opponents the learner struggles against."""

from __future__ import annotations

import numpy as np

from ..eval.elo import Payoff


def pfsp_weights(learner: str, pool: list[str], payoff: Payoff, mode: str = "squared") -> np.ndarray:
    p = np.array([payoff.win_rate(learner, o) for o in pool])
    w = (1.0 - p) ** 2 if mode == "squared" else (1.0 - p)
    w = w + 1e-3
    return w / w.sum()


def sample_opponent(learner: str, pool: list[str], payoff: Payoff, rng: np.random.Generator,
                    mode: str = "squared") -> str:
    return pool[int(rng.choice(len(pool), p=pfsp_weights(learner, pool, payoff, mode)))]
