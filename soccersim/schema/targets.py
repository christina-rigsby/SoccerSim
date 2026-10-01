"""Structural validation of targets, refs, anchors and opponent selectors (spec §3.3–3.5).

Every function returns a list of error strings, each prefixed with the location, so the
validator can report all problems in a play at once.
"""

from __future__ import annotations

from typing import Any

from .vocab import FIXED_ANCHORS, LANES, LINES, SIMPLE_SELECTORS, is_zone


class RefContext:
    """What a play declares, which references are checked against."""

    def __init__(self, role_ids: list[str], group_ids: list[str]) -> None:
        self.role_ids = set(role_ids)
        self.group_ids = set(group_ids)


def check_selector(sel: Any, ctx: RefContext, where: str) -> list[str]:
    if not isinstance(sel, str):
        return [f"{where}: opponent selector must be a string, got {sel!r}"]
    if sel in SIMPLE_SELECTORS:
        return []
    if sel.startswith("nearest_to_role:"):
        role = sel.split(":", 1)[1]
        return [] if role in ctx.role_ids else [f"{where}: selector references undefined role {role!r}"]
    if sel.startswith("in_zone:"):
        zone = sel.split(":", 1)[1]
        return [] if is_zone(zone) else [f"{where}: unknown zone id {zone!r}"]
    return [f"{where}: unknown opponent selector {sel!r}"]


def check_anchor(anchor: Any, ctx: RefContext, where: str) -> list[str]:
    if not isinstance(anchor, str):
        return [f"{where}: anchor must be a string, got {anchor!r}"]
    if anchor in FIXED_ANCHORS:
        return []
    if anchor.startswith("role:"):
        role = anchor.split(":", 1)[1]
        return [] if role in ctx.role_ids else [f"{where}: anchor references undefined role {role!r}"]
    if anchor.startswith("opp:"):
        return check_selector(anchor.split(":", 1)[1], ctx, where)
    if anchor.startswith("line:"):
        line = anchor.split(":", 1)[1]
        return [] if line in LINES else [f"{where}: unknown line {line!r}"]
    return [f"{where}: unknown anchor {anchor!r}"]


def check_ref(ref: Any, ctx: RefContext, where: str) -> list[str]:
    """Refs used by predicates: ball, ball_holder, role:R, anchor:X, opp:<sel>, line:<name>."""
    if not isinstance(ref, str):
        return [f"{where}: ref must be a string, got {ref!r}"]
    if ref in ("ball", "ball_holder"):
        return []
    if ref.startswith("anchor:"):
        return check_anchor(ref.split(":", 1)[1], ctx, where)
    if ref.startswith(("role:", "opp:", "line:")):
        return check_anchor(ref, ctx, where)
    return [f"{where}: unknown ref {ref!r}"]


def check_role(role: Any, ctx: RefContext, where: str) -> list[str]:
    if not isinstance(role, str) or role not in ctx.role_ids:
        return [f"{where}: undefined role reference {role!r}"]
    return []


def _check_region(region: Any, ctx: RefContext, where: str) -> list[str]:
    if not isinstance(region, dict):
        return [f"{where}: region must be a mapping"]
    if "zone" in region:
        extra = set(region) - {"zone"}
        errs = [f"{where}: unexpected keys {sorted(extra)}"] if extra else []
        return errs + ([] if is_zone(region["zone"]) else [f"{where}: unknown zone id {region['zone']!r}"])
    if "anchor" in region:
        extra = set(region) - {"anchor", "radius"}
        errs = [f"{where}: unexpected keys {sorted(extra)}"] if extra else []
        if not isinstance(region.get("radius"), (int, float)):
            errs.append(f"{where}: anchor region needs a numeric radius")
        return errs + check_anchor(region["anchor"], ctx, where)
    return [f"{where}: region needs 'zone' or 'anchor'"]


TARGET_FORMS = ("role", "anchor", "zone", "pc_best", "space_behind", "best_teammate", "opponent")


def check_target(t: Any, ctx: RefContext, where: str) -> list[str]:
    """Validate one target (spec §3.4)."""
    if not isinstance(t, dict):
        return [f"{where}: target must be a mapping, got {t!r}"]
    forms = [k for k in TARGET_FORMS if k in t]
    if len(forms) != 1:
        return [f"{where}: target needs exactly one of {TARGET_FORMS}, got keys {sorted(t)}"]
    form = forms[0]
    errs: list[str] = []

    def allowed(*keys: str) -> None:
        extra = set(t) - {form, *keys}
        if extra:
            errs.append(f"{where}: unexpected keys {sorted(extra)} in {form} target")

    if form == "role":
        allowed("lead")
        errs += check_role(t["role"], ctx, where)
        if "lead" in t and not isinstance(t["lead"], (int, float)):
            errs.append(f"{where}: lead must be a number")
    elif form == "anchor":
        allowed("offset", "freeze")
        errs += check_anchor(t["anchor"], ctx, where)
        off = t.get("offset", [0, 0])
        if not (isinstance(off, list) and len(off) == 2 and all(isinstance(v, (int, float)) for v in off)):
            errs.append(f"{where}: offset must be [dx, dy]")
        if "freeze" in t and t["freeze"] != "step_start":
            errs.append(f"{where}: freeze must be 'step_start'")
    elif form == "zone":
        allowed("pick")
        if not is_zone(t["zone"]):
            errs.append(f"{where}: unknown zone id {t['zone']!r}")
        if "pick" in t and t["pick"] not in ("centroid", "pc"):
            errs.append(f"{where}: pick must be 'centroid' or 'pc'")
    elif form == "pc_best":
        allowed("score")
        errs += _check_region(t["pc_best"], ctx, where)
        if t.get("score", "pc") not in ("pc", "pc_xt"):
            errs.append(f"{where}: pc_best score must be pc or pc_xt")
    elif form == "space_behind":
        allowed()
        sb = t["space_behind"]
        if not isinstance(sb, dict):
            errs.append(f"{where}: space_behind must be a mapping")
        else:
            if sb.get("line") not in LINES:
                errs.append(f"{where}: unknown line {sb.get('line')!r}")
            if sb.get("lane") not in LANES:
                errs.append(f"{where}: unknown lane {sb.get('lane')!r}")
            if not isinstance(sb.get("depth"), (int, float)):
                errs.append(f"{where}: space_behind needs numeric depth")
            extra = set(sb) - {"line", "lane", "depth"}
            if extra:
                errs.append(f"{where}: unexpected keys {sorted(extra)} in space_behind")
    elif form == "best_teammate":
        allowed()
        bt = t["best_teammate"]
        if not isinstance(bt, dict) or bt.get("score") not in ("xt", "pass_p", "pc_xt"):
            errs.append(f"{where}: best_teammate needs score in xt|pass_p|pc_xt")
        elif "zone" in bt and not is_zone(bt["zone"]):
            errs.append(f"{where}: unknown zone id {bt['zone']!r}")
    elif form == "opponent":
        allowed()
        errs += check_selector(t["opponent"], ctx, where)
    return errs
