"""Mutation operators over plays (spec §11 Phase B.2).

Operators: perturb offsets (+-2..6 m), swap an action for another in the same category,
change target types, insert or delete a step, change pass styles, re-bind roles to
different hints. Every mutant goes through the normal validator; anything invalid is
discarded, never repaired.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

import numpy as np

from ..schema.loader import play_to_dict
from ..schema.models import Play
from ..schema.validate import PlayValidationError, parse_play
from ..schema.vocab import HINTS, LANES, LINES
from .grammar import ZONES

SWAP_GROUPS = [
    ("pass", "cutback", "cross"),
    ("carry", "dribble"),
    ("run_to", "third_man_run", "decoy_run", "hold_position"),
    ("overlap", "underlap"),
]
STYLE_FOR = {"pass": ("ground", "driven", "lofted", "through"), "cross": ("whipped", "lofted", "driven_low")}
OPERATORS = ("perturb_offsets", "swap_action", "change_target", "insert_step", "delete_step", "change_style",
             "rebind_hints")


def _all_actions(d: dict) -> list[dict]:
    out = []
    for s in d["steps"]:
        out.extend(s.get("actions") or [])
        for o in s.get("choose") or []:
            out.extend(o["actions"])
    return out


def _targets(d: dict) -> list[tuple[dict, str]]:
    return [(a, k) for a in _all_actions(d) for k in ("to", "target") if isinstance(a.get(k), dict)]


def _random_target(rng: np.random.Generator, roles: list[str]) -> dict[str, Any]:
    kind = rng.choice(["role", "anchor", "zone", "pc_best", "space_behind", "best_teammate"])
    if kind == "role":
        return {"role": str(rng.choice(roles)), "lead": float(rng.choice([0, 2, 4]))}
    if kind == "anchor":
        return {"anchor": "ball", "offset": [float(rng.integers(-5, 12) * 2), float(rng.integers(-6, 7) * 2)]}
    if kind == "zone":
        return {"zone": str(rng.choice(ZONES))}
    if kind == "pc_best":
        return {"pc_best": {"zone": str(rng.choice(ZONES))}, "score": "pc_xt"}
    if kind == "space_behind":
        return {"space_behind": {"line": str(rng.choice([x for x in LINES if x.startswith("opp")])),
                                 "lane": str(rng.choice(list(LANES))), "depth": float(rng.choice([4, 6, 8, 10]))}}
    return {"best_teammate": {"score": str(rng.choice(["xt", "pass_p", "pc_xt"]))}}


def apply_operator(d: dict, op: str, rng: np.random.Generator) -> bool:
    """Mutate ``d`` in place; return False if the operator does not apply."""
    roles = [r["id"] for r in d["roles"]]
    if op == "perturb_offsets":
        anchors = [(a, k) for a, k in _targets(d) if "offset" in a[k]]
        if not anchors:
            return False
        a, k = anchors[rng.integers(len(anchors))]
        off = a[k]["offset"]
        i = int(rng.integers(2))
        off[i] = float(off[i] + rng.choice([-1, 1]) * rng.integers(1, 4) * 2)
        return True
    if op == "swap_action":
        acts = [a for a in _all_actions(d) if any(a["type"] in g for g in SWAP_GROUPS)]
        if not acts:
            return False
        a = acts[rng.integers(len(acts))]
        group = next(g for g in SWAP_GROUPS if a["type"] in g)
        new = str(rng.choice([t for t in group if t != a["type"]]))
        a["type"] = new
        for k in ("style", "one_touch", "speed", "arrive_with", "protect", "beat"):
            a.pop(k, None)
        if new in STYLE_FOR:
            a["style"] = str(rng.choice(STYLE_FOR[new]))
        return True
    if op == "change_target":
        tg = [(a, k) for a, k in _targets(d) if k == "to"]
        if not tg:
            return False
        a, k = tg[rng.integers(len(tg))]
        a[k] = _random_target(rng, roles)
        return True
    if op == "insert_step":
        if len(d["steps"]) >= 6:
            return False
        i = int(rng.integers(len(d["steps"])))
        new = copy.deepcopy(d["steps"][i])
        new["id"] = f"{new['id']}x{rng.integers(1000)}"
        new.pop("next", None)
        if str(new.get("on_timeout", "")).startswith("goto:"):
            new["on_timeout"] = "abort"
        new.setdefault("timeout_s", 3.0)
        d["steps"].insert(i + 1, new)
        return True
    if op == "delete_step":
        if len(d["steps"]) < 2:
            return False
        i = int(rng.integers(len(d["steps"])))
        gone = d["steps"].pop(i)["id"]
        for s in d["steps"]:
            if s.get("next") == gone:
                s.pop("next")
            if s.get("on_timeout") == f"goto:{gone}":
                s["on_timeout"] = "next"
        return True
    if op == "change_style":
        acts = [a for a in _all_actions(d) if a["type"] in STYLE_FOR]
        if not acts:
            return False
        a = acts[rng.integers(len(acts))]
        a["style"] = str(rng.choice([s for s in STYLE_FOR[a["type"]] if s != a.get("style")]))
        return True
    if op == "rebind_hints":
        r = d["roles"][rng.integers(len(d["roles"]))]
        if "GK" in r.get("hints", []):
            return False
        r["hints"] = list(rng.choice([h for h in HINTS if h != "GK"], size=int(rng.integers(1, 4)), replace=False))
        return True
    raise ValueError(op)


def mutate(play: Play, rng: np.random.Generator, n_ops: int = 2) -> Play | None:
    """One mutant of ``play`` (1..n_ops operators), validated; ``None`` if invalid."""
    d = play_to_dict(play)
    ops = []
    for _ in range(int(rng.integers(1, n_ops + 1))):
        op = str(rng.choice(OPERATORS))
        if apply_operator(d, op, rng):
            ops.append(op)
    if not ops:
        return None
    digest = hashlib.sha1(json.dumps(d, sort_keys=True).encode()).hexdigest()[:8]
    d["id"] = f"{play.id}__m{digest}"
    d["source"] = "generated"
    d["provenance"] = {"parent": play.id, "operators": ops}
    d["cooldown_s"] = 0.0
    try:
        return parse_play(d)
    except PlayValidationError:
        return None
