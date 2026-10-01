"""Cross-reference validation of plays (spec §4.6). Fails loudly, never repairs.

Generated plays (Module 3) pass through exactly this function; anything that fails is
discarded by the caller.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from .models import Action, Play
from .predicates import check_predicate
from .targets import RefContext, check_role, check_selector, check_target
from .vocab import ACTION_SPECS, CAPABILITIES, EVENT_TYPES, HINTS, LANES, LINES, POSSESSION_PHASES


class PlayValidationError(ValueError):
    """A play failed validation. ``errors`` lists every problem found."""

    def __init__(self, play_id: str, errors: list[str], source: str | None = None) -> None:
        self.play_id = play_id
        self.errors = errors
        self.source = source
        where = f" ({source})" if source else ""
        super().__init__(f"play {play_id!r}{where} is invalid:\n  - " + "\n  - ".join(errors))


def _check_param(kind: object, value: Any, ctx: RefContext, where: str) -> list[str]:
    if kind == "target":
        return check_target(value, ctx, where)
    if kind == "role":
        return check_role(value, ctx, where)
    if kind == "opp_selector":
        return check_selector(value, ctx, where)
    if kind == "line":
        return [] if value in LINES else [f"{where}: unknown line {value!r}"]
    if kind == "lane":
        return [] if value in LANES else [f"{where}: unknown lane {value!r}"]
    if kind == "number":
        ok = isinstance(value, (int, float)) and not isinstance(value, bool)
        return [] if ok else [f"{where}: must be a number, got {value!r}"]
    if kind == "bool":
        return [] if isinstance(value, bool) else [f"{where}: must be true/false, got {value!r}"]
    if kind == "event":
        return [] if value in EVENT_TYPES else [f"{where}: unknown event type {value!r}"]
    if isinstance(kind, tuple):
        return [] if value in kind else [f"{where}: must be one of {kind}, got {value!r}"]
    return [f"{where}: unknown parameter kind {kind!r}"]  # pragma: no cover


def check_action(action: Action, ctx: RefContext, where: str) -> list[str]:
    errs: list[str] = []
    spec = ACTION_SPECS.get(action.type)
    if spec is None:
        return [f"{where}: unknown action type {action.type!r}"]
    if action.role is not None:
        errs += check_role(action.role, ctx, where + ".role")
    else:
        actor = action.actor
        if actor == "ball_holder":
            pass
        elif isinstance(actor, dict) and set(actor) == {"nearest_to_ball_in"}:
            group = actor["nearest_to_ball_in"]
            if group not in ctx.group_ids:
                errs.append(f"{where}.actor: nearest_to_ball_in must name a group role, got {group!r}")
        else:
            errs.append(f"{where}.actor: must be ball_holder or {{nearest_to_ball_in: <group>}}, got {actor!r}")
    params = action.params
    for name, (kind, required) in spec.items():
        if name not in params:
            if required:
                errs.append(f"{where}: action {action.type!r} is missing required param {name!r}")
            continue
        errs += _check_param(kind, params[name], ctx, f"{where}.{name}")
    unknown = set(params) - set(spec)
    if unknown:
        errs.append(f"{where}: action {action.type!r} has unknown params {sorted(unknown)}")
    return errs


def _step_graph_errors(play: Play) -> list[str]:
    """``goto``/``next`` targets exist; cycles are only allowed through timed-out steps."""
    errs: list[str] = []
    ids = [s.id for s in play.steps]
    if len(set(ids)) != len(ids):
        errs.append(f"duplicate step ids: {sorted({i for i in ids if ids.count(i) > 1})}")
    known = set(ids)
    edges: dict[str, set[str]] = {sid: set() for sid in ids}
    for i, step in enumerate(play.steps):
        where = f"steps[{step.id}]"
        default_next = ids[i + 1] if i + 1 < len(ids) else None
        nxt = step.next
        if nxt is not None and nxt != "end" and nxt not in known:
            errs.append(f"{where}.next: step {nxt!r} does not exist")
        elif nxt is None and default_next:
            edges[step.id].add(default_next)
        elif nxt not in (None, "end"):
            edges[step.id].add(nxt)
        ot = step.on_timeout
        if ot in ("abort", "next"):
            if ot == "next" and default_next and nxt is None:
                edges[step.id].add(default_next)
        elif ot.startswith("goto:"):
            tgt = ot.split(":", 1)[1]
            if tgt not in known:
                errs.append(f"{where}.on_timeout: goto target {tgt!r} does not exist")
            else:
                edges[step.id].add(tgt)
        else:
            errs.append(f"{where}.on_timeout: must be abort | next | goto:<step_id>, got {ot!r}")

    # Any cycle must contain only steps with a timeout, which bounds how long it can spin.
    timed = {s.id for s in play.steps if s.timeout_s is not None}
    colour: dict[str, int] = {}

    def visit(node: str, stack: list[str]) -> None:
        colour[node] = 1
        for nb in edges.get(node, ()):
            if colour.get(nb) == 1:
                cycle = stack[stack.index(nb):] + [node] if nb in stack else [node, nb]
                if not all(c in timed for c in cycle):
                    errs.append(f"step graph has a cycle without timeouts: {' -> '.join(cycle + [nb])}")
            elif colour.get(nb) is None:
                visit(nb, stack + [node])
        colour[node] = 2

    for sid in ids:
        if colour.get(sid) is None:
            visit(sid, [])
    return errs


def validate_play(play: Play, source: str | None = None) -> Play:
    """Validate ``play`` and return it, or raise :class:`PlayValidationError`."""
    errs: list[str] = []
    role_ids = [r.id for r in play.roles]
    if not role_ids:
        errs.append("a play needs at least one role")
    if len(set(role_ids)) != len(role_ids):
        errs.append(f"duplicate role ids: {sorted({r for r in role_ids if role_ids.count(r) > 1})}")
    groups = [r.id for r in play.roles if r.group]
    ctx = RefContext(role_ids, groups)

    ball_roles = [r.id for r in play.roles if r.starts_with_ball]
    if len(ball_roles) > 1:
        errs.append(f"starts_with_ball is set on more than one role: {ball_roles}")
    if ball_roles and play.phase not in POSSESSION_PHASES:
        errs.append(f"starts_with_ball is only allowed in possession phases, not {play.phase!r}")
    if play.n_slots > 11:
        errs.append(f"play needs {play.n_slots} players but a team has 11")

    for r in play.roles:
        where = f"roles[{r.id}]"
        for h in r.hints:
            if h not in HINTS:
                errs.append(f"{where}: unknown position hint {h!r}")
        for field in ("requires", "prefers"):
            for cap, v in getattr(r, field).items():
                if cap not in CAPABILITIES:
                    errs.append(f"{where}.{field}: unknown capability {cap!r}")
                elif not 0.0 <= v <= 1.0 and field == "requires":
                    errs.append(f"{where}.requires: {cap} minimum must be in [0, 1]")
        if r.group and r.starts_with_ball:
            errs.append(f"{where}: a group role cannot start with the ball")

    errs += check_predicate(play.triggers, ctx, "triggers", in_trigger=True)
    for i, hc in enumerate(play.hard_constraints):
        errs += check_predicate(hc, ctx, f"hard_constraints[{i}]")
    errs += check_predicate(play.success, ctx, "success")
    errs += check_predicate(play.abort, ctx, "abort")

    if not play.steps:
        errs.append("a play needs at least one step")
    for step in play.steps:
        where = f"steps[{step.id}]"
        if (step.actions is None) == (step.choose is None):
            errs.append(f"{where}: must have exactly one of 'actions' or 'choose'")
        if step.start_when is not None:
            errs += check_predicate(step.start_when, ctx, where + ".start_when")
        errs += check_predicate(step.done_when, ctx, where + ".done_when")
        for j, a in enumerate(step.actions or []):
            errs += check_action(a, ctx, f"{where}.actions[{j}]")
        for k, opt in enumerate(step.choose or []):
            errs += check_predicate(opt.when, ctx, f"{where}.choose[{k}].when")
            if not opt.actions:
                errs.append(f"{where}.choose[{k}]: needs at least one action")
            for j, a in enumerate(opt.actions):
                errs += check_action(a, ctx, f"{where}.choose[{k}].actions[{j}]")
    errs += _step_graph_errors(play)

    if errs:
        raise PlayValidationError(play.id, errs, source)
    return play


def parse_play(data: dict[str, Any], source: str | None = None) -> Play:
    """Parse a raw mapping into a validated :class:`Play`.

    Pydantic shape errors are re-raised as :class:`PlayValidationError` so callers see
    one error type whatever went wrong.
    """
    play_id = str(data.get("id", "<no id>")) if isinstance(data, dict) else "<not a mapping>"
    if not isinstance(data, dict):
        raise PlayValidationError(play_id, ["play file must be a mapping"], source)
    try:
        play = Play.model_validate(data)
    except ValidationError as exc:
        errors = []
        for e in exc.errors():
            loc = ".".join(str(p) for p in e["loc"])
            errors.append(f"{loc}: {e['msg']}")
        raise PlayValidationError(play_id, errors, source) from None
    return validate_play(play, source)
