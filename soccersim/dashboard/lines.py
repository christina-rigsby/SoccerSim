"""Dynamic team lines by 1-D k-means over outfield x (spec §3.2).

"First" is the line the attacking team meets first. In a team's own frame (attacking
+x) the opponent's first line is its most advanced (lowest x) and ``opp_last_line`` is
the deepest opponent outfielder (the offside line, bar the keeper). Our first line is
our most advanced (highest x) and ``our_last_line`` our deepest outfielder.
"""

from __future__ import annotations

import numpy as np


def kmeans_1d(xs: np.ndarray, k: int = 3, iters: int = 20, merge_below: float = 3.0) -> np.ndarray:
    """Sorted cluster centres. Collapsing clusters are merged, so fewer than ``k`` may return."""
    xs = np.sort(np.asarray(xs, dtype=float))
    if len(xs) == 0:
        return np.zeros(0)
    k = min(k, len(xs))
    centres = np.quantile(xs, (np.arange(k) + 0.5) / k)
    for _ in range(iters):
        assign = np.argmin(np.abs(xs[:, None] - centres[None, :]), axis=1)
        new = np.array([xs[assign == j].mean() if np.any(assign == j) else centres[j] for j in range(k)])
        if np.allclose(new, centres):
            break
        centres = new
    centres = np.sort(centres)
    merged = [centres[0]]
    for c in centres[1:]:
        if c - merged[-1] < merge_below:
            merged[-1] = 0.5 * (merged[-1] + c)
        else:
            merged.append(c)
    return np.array(merged)


def team_lines(us_x: np.ndarray, them_x: np.ndarray) -> dict[str, float]:
    """Line x-positions in our frame from outfield x of each team (keepers excluded)."""
    oc = kmeans_1d(them_x)
    uc = kmeans_1d(us_x)

    def pick(c: np.ndarray, i: int) -> float:
        return float(c[min(i, len(c) - 1)]) if len(c) else 0.0

    return {
        "opp_first_line": pick(oc, 0),
        "opp_second_line": pick(oc, 1) if len(oc) >= 3 else float(np.mean(oc)) if len(oc) else 0.0,
        "opp_last_line": float(np.max(them_x)) if len(them_x) else 52.5,
        "our_first_line": pick(uc[::-1], 0),
        "our_second_line": pick(uc[::-1], 1) if len(uc) >= 3 else float(np.mean(uc)) if len(uc) else 0.0,
        "our_last_line": float(np.min(us_x)) if len(us_x) else -52.5,
    }


def line_height(name: str, x: float) -> float:
    """Distance of a line from the defending team's own goal line."""
    return 52.5 - x if name.startswith("opp_") else x + 52.5
