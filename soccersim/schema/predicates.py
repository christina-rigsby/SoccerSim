"""Structural validation of predicates (spec §4.5).

Predicates are structured YAML: combinators ``all`` / ``any`` / ``not``, the literal
string ``always``, or a single-key mapping naming one predicate. Comparisons use
``lt, le, gt, ge, eq``.
"""

from __future__ import annotations

from typing import Any

from .targets import RefContext, check_ref, check_role, check_target
from .vocab import COMPARATORS, EVENT_TYPES, LINES, PREDICATE_KEYS, is_zone


def _check_cmp(body: dict, where: str, required: bool = True, allowed_extra: tuple[str, ...] = ()) -> list[str]:
    cmps = [k for k in COMPARATORS if k in body]
    errs = []
    if required and not cmps:
        errs.append(f"{where}: needs a comparison (one of {COMPARATORS})")
    for k in cmps:
        if not isinstance(body[k], (int, float)):
            errs.append(f"{where}: comparison {k} must be numeric")
    extra = set(body) - set(COMPARATORS) - set(allowed_extra)
    if extra:
        errs.append(f"{where}: unexpected keys {sorted(extra)}")
    return errs


def check_predicate(p: Any, ctx: RefContext, where: str, in_trigger: bool = False) -> list[str]:
    """Validate a predicate tree. ``in_trigger`` enforces ``within_s`` on events."""
    if p == "always":
        return []
    if isinstance(p, str):
        return [f"{where}: unknown predicate literal {p!r} (only 'always' is allowed)"]
    if not isinstance(p, dict):
        return [f"{where}: predicate must be a mapping or 'always', got {p!r}"]
    if len(p) != 1:
        return [f"{where}: predicate mapping must have exactly one key, got {sorted(p)}"]
    (key, body), = p.items()
    here = f"{where}.{key}"

    if key == "always":
        return [f"{here}: 'always' must be the literal string always, not a mapping ({{always: {body!r}}})"]
    if key in ("all", "any"):
        if not isinstance(body, list):
            return [f"{here}: must be a list"]
        errs: list[str] = []
        for i, sub in enumerate(body):
            errs += check_predicate(sub, ctx, f"{here}[{i}]", in_trigger)
        return errs
    if key == "not":
        return check_predicate(body, ctx, here, in_trigger)
    if key not in PREDICATE_KEYS:
        return [f"{here}: unknown predicate {key!r}"]

    if key == "possession":
        return [] if body in ("us", "them", "loose") else [f"{here}: must be us|them|loose"]
    if key == "has_ball":
        if body in ("teammate", "opponent"):
            return []
        return check_role(body, ctx, here)
    if key == "ball_in_zone":
        zones = body if isinstance(body, list) else [body]
        return [f"{here}: unknown zone id {z!r}" for z in zones if not is_zone(z)]
    if key == "role_in_zone":
        if not isinstance(body, dict):
            return [f"{here}: must be a mapping"]
        errs = check_role(body.get("role"), ctx, here)
        if not is_zone(body.get("zone")):
            errs.append(f"{here}: unknown zone id {body.get('zone')!r}")
        return errs
    if key in ("dist", "ahead_of"):
        if not isinstance(body, dict):
            return [f"{here}: must be a mapping"]
        errs = check_ref(body.get("a"), ctx, here + ".a") + check_ref(body.get("b"), ctx, here + ".b")
        if key == "dist":
            errs += _check_cmp(body, here, allowed_extra=("a", "b"))
        else:
            extra = set(body) - {"a", "b", "by"}
            if extra:
                errs.append(f"{here}: unexpected keys {sorted(extra)}")
        return errs
    if key == "pressure_on":
        if not isinstance(body, dict):
            return [f"{here}: must be a mapping"]
        return check_ref(body.get("ref"), ctx, here) + _check_cmp(body, here, allowed_extra=("ref",))
    if key == "lane_open":
        if not isinstance(body, dict):
            return [f"{here}: must be a mapping"]
        frm = body.get("from")
        errs = [] if frm == "ball_holder" else check_role(frm, ctx, here + ".from")
        errs += check_target(body.get("to"), ctx, here + ".to")
        if not isinstance(body.get("min_p"), (int, float)):
            errs.append(f"{here}: needs numeric min_p")
        extra = set(body) - {"from", "to", "min_p"}
        if extra:
            errs.append(f"{here}: unexpected keys {sorted(extra)}")
        return errs
    if key == "pc_at":
        if not isinstance(body, dict):
            return [f"{here}: must be a mapping"]
        return check_target(body.get("target"), ctx, here + ".target") + _check_cmp(
            body, here, allowed_extra=("target",)
        )
    if key == "xg":
        if not isinstance(body, dict):
            return [f"{here}: must be a mapping"]
        return check_ref(body.get("ref"), ctx, here) + _check_cmp(body, here, allowed_extra=("ref",))
    if key == "line_height":
        if not isinstance(body, dict):
            return [f"{here}: must be a mapping"]
        errs = [] if body.get("line") in LINES else [f"{here}: unknown line {body.get('line')!r}"]
        return errs + _check_cmp(body, here, allowed_extra=("line",))
    if key == "count_in_zone":
        if not isinstance(body, dict):
            return [f"{here}: must be a mapping"]
        errs = [] if body.get("team") in ("us", "them") else [f"{here}: team must be us|them"]
        if not is_zone(body.get("zone")):
            errs.append(f"{here}: unknown zone id {body.get('zone')!r}")
        return errs + _check_cmp(body, here, allowed_extra=("team", "zone"))
    if key == "goal_side_count":
        if not isinstance(body, dict):
            return [f"{here}: must be a mapping"]
        errs = [] if body.get("team") in ("us", "them") else [f"{here}: team must be us|them"]
        return errs + _check_cmp(body, here, allowed_extra=("team",))
    if key == "teammates_near":
        if not isinstance(body, dict):
            return [f"{here}: must be a mapping"]
        errs = check_ref(body.get("ref"), ctx, here)
        if not isinstance(body.get("radius"), (int, float)):
            errs.append(f"{here}: needs numeric radius")
        return errs + _check_cmp(body, here, allowed_extra=("ref", "radius"))
    if key == "onside":
        return check_role(body, ctx, here)
    if key == "event":
        if isinstance(body, str):
            errs = [] if body in EVENT_TYPES else [f"{here}: unknown event type {body!r}"]
            if in_trigger:
                errs.append(f"{here}: events in triggers need an explicit within_s window")
            return errs
        if not isinstance(body, dict):
            return [f"{here}: must be an event type or {{type, within_s}}"]
        errs = [] if body.get("type") in EVENT_TYPES else [f"{here}: unknown event type {body.get('type')!r}"]
        if "within_s" in body and not isinstance(body["within_s"], (int, float)):
            errs.append(f"{here}: within_s must be numeric")
        if in_trigger and "within_s" not in body:
            errs.append(f"{here}: events in triggers need an explicit within_s window")
        extra = set(body) - {"type", "within_s"}
        if extra:
            errs.append(f"{here}: unexpected keys {sorted(extra)}")
        return errs
    if key in ("ball_beyond_line", "ball_behind_line"):
        if not isinstance(body, dict):
            return [f"{here}: must be a mapping"]
        errs = [] if body.get("line") in LINES else [f"{here}: unknown line {body.get('line')!r}"]
        extra = set(body) - {"line", "by"}
        if extra:
            errs.append(f"{here}: unexpected keys {sorted(extra)}")
        return errs
    if key in ("elapsed_s", "step_elapsed_s"):
        if not isinstance(body, dict):
            return [f"{here}: must be a comparison mapping"]
        return _check_cmp(body, here)
    if key == "game":
        if not isinstance(body, dict) or not body:
            return [f"{here}: must be a non-empty mapping"]
        errs = []
        for k, v in body.items():
            if k not in ("score_diff", "minute"):
                errs.append(f"{here}: unknown game field {k!r}")
            elif not isinstance(v, dict):
                errs.append(f"{here}.{k}: must be a comparison mapping")
            else:
                errs += _check_cmp(v, f"{here}.{k}")
        return errs
    return [f"{here}: unhandled predicate"]  # pragma: no cover


def iter_atoms(p: Any):
    """Yield every atomic predicate (single-key mapping) in a predicate tree."""
    if isinstance(p, dict) and len(p) == 1:
        (key, body), = p.items()
        if key in ("all", "any") and isinstance(body, list):
            for sub in body:
                yield from iter_atoms(sub)
            return
        if key == "not":
            yield from iter_atoms(body)
            return
        yield key, body
