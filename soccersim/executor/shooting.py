"""Shoot when on: a ball carrier with a good, clear chance shoots, whatever play is running.

Before this rule a player only ever shot inside the few plays with a ``shoot`` step, so a
player through on goal during, say, a recycling play would pass instead. The rule applies to
every team (configs/ranking.yaml: ``shooting``):

- the chance must be good: xG from where the carrier stands, already reduced by how close the
  nearest defender is (:func:`soccersim.sim.shots.xg`), is at least ``min_xg``;
- the shot must be clear: no outfield opponent stands in the cone between the ball and the two
  posts within ``block_range_m`` of the shooter (widened by ``cone_margin_m``). The simulator
  does not model blocked shots, so without this check a shot through a defender would count;
- the carrier has had the ball for at least ``settle_s`` (no shooting on the first touch);
- the goalkeeper never shoots.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np

from ..config import load_config
from ..dashboard.team_state import TeamView

GOAL_X = 52.5
POST_Y = 3.66


@lru_cache(maxsize=1)
def shooting_config() -> dict:
    return dict(load_config("ranking").get("shooting") or {"enabled": False})


def shot_blockers(view: TeamView, shooter: int, block_range: float, margin: float) -> list[int]:
    """Outfield opponents inside the shooting cone (ball -> both posts) within ``block_range``."""
    s = view.pos[shooter]
    left, right = np.array([GOAL_X, POST_Y + margin]), np.array([GOAL_X, -POST_Y - margin])
    out = []
    for o in view.outfield(view.them):
        p = view.pos[o]
        d = p - s
        if np.hypot(*d) > block_range or d[0] <= 0:
            continue
        # Inside the triangle shooter-left post-right post (same side of each edge as the centroid).
        tri = (s, left, right)
        sign = [np.sign((b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0]))
                for a, b in zip(tri, tri[1:] + tri[:1], strict=True)]
        if all(x >= 0 for x in sign) or all(x <= 0 for x in sign):
            out.append(int(o))
    return out


def shot_is_on(view: TeamView, cfg: dict | None = None) -> bool:
    """Whether our ball carrier should shoot now (see the module docstring)."""
    cfg = cfg if cfg is not None else shooting_config()
    if not cfg.get("enabled", False) or view.possession != "us":
        return False
    h = view.holder
    if h < 0 or view.state.kinds[h] == "GK":
        return False
    if view.t - view.state.ball.owner_since < float(cfg.get("settle_s", 0.2)):
        return False
    if view.xg_of(h) < float(cfg.get("min_xg", 0.1)):
        return False
    return not shot_blockers(view, h, float(cfg.get("block_range_m", 10.0)), float(cfg.get("cone_margin_m", 0.5)))
