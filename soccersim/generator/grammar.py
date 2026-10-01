"""The play grammar: tokens, and a generator-coroutine that both constrains decoding and
builds the play (spec §10.2).

``PHASE OBJ TEMPO RISK [ROLE hint* req*]+ [STEP [START pred] (ACTS | CHOOSE) DONE pred TIMEOUT]+
SUCCESS pred ABORT pred END``

:func:`play_program` is a Python generator. Each ``yield`` hands out the set of token ids
that keep the sequence schema-valid; the caller sends back the chosen id. When the
program returns, its ``StopIteration.value`` is the play as a YAML-ready dict. The same
program therefore drives three things:

- grammar-constrained decoding (mask logits to the yielded set),
- detokenisation (feed a recorded token sequence; anything off-grammar raises),
- the length budget (structures are only opened while enough tokens remain to close them).

Roles are always ``R1..Rn`` with ``R1`` starting with the ball (generated plays are
possession plays); steps are ``s1..sn`` in order, so the step graph is a chain.
"""

from __future__ import annotations

import hashlib
from collections.abc import Generator
from typing import Any

from ..schema.vocab import CAPABILITIES, EVENT_TYPES, HINTS, LANES, LINES

MAX_ROLES = 7
MAX_STEPS = 5
MAX_ACTIONS = 4
MAX_ATOMS = 3
MAX_OPTIONS = 3

PHASES = ("in_possession", "transition_attack", "set_piece")
OBJECTIVES = ("retain_possession", "progress_ball", "create_chance", "score")
TEMPOS = ("slow", "medium", "fast")
RISK_BINS = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7)
REQ_BINS = (0.3, 0.4, 0.5, 0.55, 0.6, 0.65, 0.7)
TIMEOUT_BINS = (0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0)
ELAPSED_BINS = (0.3, 0.5, 0.8, 1.0, 1.5, 2.0, 3.0)
DIST_BINS = (1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 12.0, 14.0, 16.0, 20.0)
PROB_BINS = (0.3, 0.4, 0.45, 0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9)
XG_BINS = (0.04, 0.06, 0.08, 0.1, 0.12, 0.15, 0.2)
DUR_BINS = (0.5, 0.8, 1.0, 1.5, 2.0, 3.0)
DEPTH_BINS = (4.0, 6.0, 8.0, 10.0, 12.0)
LEAD_BINS = (0.0, 2.0, 3.0, 4.0, 6.0)
OFFSETS = tuple(range(-30, 31, 2))
ZONES = (
    *[f"{b}.{l}" for b in ("own_third", "mid_own", "mid_opp", "final_third") for l in LANES],
    *[f"{b}.*" for b in ("own_third", "mid_own", "mid_opp", "final_third")],
    "box", "zone14", "cutback_zone", "near_post_area", "far_post_area",
)
ANCHORS = ("ball", "goal", "near_post", "far_post", "penalty_spot", "byline_near", "own_goal")
SELECTORS = ("ball_carrier", "nearest_to_ball", "nearest_receiver", "second_receiver", "most_dangerous")
PASS_STYLES = ("ground", "driven", "lofted", "through")
CROSS_STYLES = ("whipped", "lofted", "driven_low")
SPEEDS = ("jog", "fast", "max")
ANGLES = ("back_inside", "back_outside", "square", "forward")
PLACEMENTS = ("auto", "near", "far")
STEP_EVENTS = ("pass_completed", "pass_intercepted", "shot_taken", "possession_lost", "ball_out", "goal")

ACTION_TYPES = (
    "pass", "cross", "cutback", "carry", "dribble", "shoot", "hold_up", "clear",
    "run_to", "overlap", "underlap", "third_man_run", "spin_in_behind", "check_to_ball", "decoy_run",
    "support", "hold_width", "hold_position",
)
ATOMS = (
    "has_ball", "possession_us", "possession_them", "event", "step_elapsed_gt", "ball_in_zone", "pressure_lt",
    "pressure_gt", "lane_open", "pc_at_gt", "xg_gt", "ahead_of", "dist_lt", "onside", "ball_beyond",
)

# -- vocabulary ------------------------------------------------------------------------------

SPECIAL = ["<pad>", "<bos>", "<eos>"]
STRUCT = ["ROLE", "END_ROLES", "STEP", "START", "NOSTART", "ACTS", "CHOOSE", "WHEN", "ELSE", "END_OPT",
          "ACT", "END_ACTS", "DONE", "SUCCESS", "ABORT", "ALL", "ANY", "NOT", "END_GROUP", "ALWAYS",
          "END_STEPS", "BH", "BALL_REF", "NOARRIVE", "ARRIVE", "NOZONE", "ZONE_SEL", "OT0", "OT1",
          "END_HINTS", "END_REQ", "FREEZE", "LIVE"]


def _build_vocab() -> list[str]:
    v = list(SPECIAL) + STRUCT
    v += [f"PHASE:{p}" for p in PHASES] + [f"OBJ:{o}" for o in OBJECTIVES] + [f"TEMPO:{t}" for t in TEMPOS]
    v += [f"RISK:{b}" for b in RISK_BINS] + [f"HINT:{h}" for h in HINTS]
    v += [f"REQ:{c}" for c in CAPABILITIES] + [f"RBIN:{b}" for b in REQ_BINS]
    v += [f"R{i}" for i in range(1, MAX_ROLES + 1)]
    v += [f"TYPE:{t}" for t in ACTION_TYPES] + [f"P:{a}" for a in ATOMS]
    v += [f"TO:{b}" for b in TIMEOUT_BINS] + [f"EL:{b}" for b in ELAPSED_BINS] + [f"D:{b}" for b in DIST_BINS]
    v += [f"PR:{b}" for b in PROB_BINS] + [f"XG:{b}" for b in XG_BINS] + [f"DUR:{b}" for b in DUR_BINS]
    v += [f"DEPTH:{b}" for b in DEPTH_BINS] + [f"LEAD:{b}" for b in LEAD_BINS] + [f"OFF:{o}" for o in OFFSETS]
    v += [f"Z:{z}" for z in ZONES] + [f"A:{a}" for a in ANCHORS] + [f"SEL:{s}" for s in SELECTORS]
    v += [f"LINE:{x}" for x in LINES] + [f"LANE:{x}" for x in LANES] + [f"EV:{e}" for e in STEP_EVENTS]
    v += [f"PS:{s}" for s in PASS_STYLES] + [f"CS:{s}" for s in CROSS_STYLES] + [f"SPD:{s}" for s in SPEEDS]
    v += [f"ANG:{a}" for a in ANGLES] + [f"PL:{p}" for p in PLACEMENTS]
    v += ["T:role", "T:anchor", "T:zone", "T:zone_c", "T:pc_best", "T:space_behind", "T:best_teammate",
          "T:opponent", "SC:pc", "SC:pc_xt", "SC:xt", "SC:pass_p"]
    assert all(e in EVENT_TYPES for e in STEP_EVENTS)
    return v


VOCAB: list[str] = _build_vocab()
TOK: dict[str, int] = {t: i for i, t in enumerate(VOCAB)}
PAD, BOS, EOS = TOK["<pad>"], TOK["<bos>"], TOK["<eos>"]
VOCAB_SIZE = len(VOCAB)


def ids(*names: str) -> frozenset[int]:
    return frozenset(TOK[n] for n in names)


def prefixed(prefix: str) -> frozenset[int]:
    return frozenset(i for t, i in TOK.items() if t.startswith(prefix))


def _val(tok: int) -> str:
    return VOCAB[tok].split(":", 1)[1]


def _num(tok: int) -> float:
    return float(_val(tok))


class Budget:
    """Tracks remaining tokens so the program only opens structures it can close."""

    def __init__(self, max_len: int) -> None:
        self.left = max_len

    def take(self) -> None:
        self.left -= 1

    def allow(self, reserve: int) -> bool:
        return self.left > reserve


Program = Generator[frozenset[int], int, Any]

# Worst-case token costs of one atom / predicate group / action, and the minimal cost of
# closing a step or the play. A structure is only opened while the budget can still pay
# for it plus the minimal close of everything after it, so every sequence terminates
# within ``max_len``.
R_ATOM = 9
R_PRED = 2 + MAX_ATOMS * R_ATOM
R_ACT = 14
R_TAIL_MIN = 8            # END_STEPS SUCCESS ALWAYS ABORT ALWAYS <eos> + slack
STEP_MIN = 22             # STEP NOSTART ACTS <one action> END_ACTS DONE ALWAYS TO
REST_OF_STEP = 1 + R_ACT + 1 + 3


def play_program(max_len: int = 320) -> Program:
    """The grammar. Yields allowed token-id sets; returns the play dict."""
    b = Budget(max_len)

    def ask(allowed: frozenset[int]):
        tok = yield allowed
        if tok not in allowed:
            raise ValueError(f"token {VOCAB[tok] if 0 <= tok < VOCAB_SIZE else tok!r} not allowed here")
        b.take()
        return tok

    yield from ask(ids("<bos>"))
    phase = _val((yield from ask(prefixed("PHASE:"))))
    objective = _val((yield from ask(prefixed("OBJ:"))))
    tempo = _val((yield from ask(prefixed("TEMPO:"))))
    risk = _num((yield from ask(prefixed("RISK:"))))

    # Roles.
    roles: list[dict] = []
    while True:
        can_more = len(roles) < MAX_ROLES and b.allow(10 + STEP_MIN + R_TAIL_MIN)
        opts = set()
        if can_more:
            opts.add(TOK["ROLE"])
        if roles:
            opts.add(TOK["END_ROLES"])
        t = yield from ask(frozenset(opts))
        if t == TOK["END_ROLES"]:
            break
        role: dict[str, Any] = {"id": f"R{len(roles) + 1}", "hints": []}
        if not roles:
            role["starts_with_ball"] = True
        while True:
            opts = set(prefixed("HINT:")) - {TOK[f"HINT:{h}"] for h in role["hints"]} if len(role["hints"]) < 3 \
                else set()
            if role["hints"]:
                opts.add(TOK["END_HINTS"])
            t = yield from ask(frozenset(opts))
            if t == TOK["END_HINTS"]:
                break
            role["hints"].append(_val(t))
        req: dict[str, float] = {}
        while True:
            opts = set(prefixed("REQ:")) - {TOK[f"REQ:{c}"] for c in req} if len(req) < 2 else set()
            opts.add(TOK["END_REQ"])
            t = yield from ask(frozenset(opts))
            if t == TOK["END_REQ"]:
                break
            cap = _val(t)
            req[cap] = _num((yield from ask(prefixed("RBIN:"))))
        if req:
            role["requires"] = req
        roles.append(role)
    n_roles = len(roles)
    role_refs = frozenset(TOK[f"R{i}"] for i in range(1, n_roles + 1))

    def role_ref():
        return VOCAB[(yield from ask(role_refs))]

    # -- targets ----------------------------------------------------------------------
    def target():
        t = yield from ask(ids("T:role", "T:anchor", "T:zone", "T:zone_c", "T:pc_best", "T:space_behind",
                                "T:best_teammate", "T:opponent"))
        kind = VOCAB[t][2:]
        if kind == "role":
            r = yield from role_ref()
            lead = _num((yield from ask(prefixed("LEAD:"))))
            return {"role": r, **({"lead": lead} if lead else {})}
        if kind == "anchor":
            a = yield from ask(prefixed("A:") | role_refs | prefixed("LINE:"))
            name = VOCAB[a]
            anchor = name[2:] if name.startswith("A:") else (f"role:{name}" if name.startswith("R") else
                                                              f"line:{name[5:]}")
            dx = _num((yield from ask(prefixed("OFF:"))))
            dy = _num((yield from ask(prefixed("OFF:"))))
            fr = yield from ask(ids("FREEZE", "LIVE"))
            out = {"anchor": anchor, "offset": [dx, dy]}
            if fr == TOK["FREEZE"]:
                out["freeze"] = "step_start"
            return out
        if kind in ("zone", "zone_c"):
            z = _val((yield from ask(prefixed("Z:"))))
            return {"zone": z, **({"pick": "centroid"} if kind == "zone_c" else {})}
        if kind == "pc_best":
            z = _val((yield from ask(prefixed("Z:"))))
            sc = _val((yield from ask(ids("SC:pc", "SC:pc_xt"))))
            return {"pc_best": {"zone": z}, "score": sc}
        if kind == "space_behind":
            line = _val((yield from ask(prefixed("LINE:"))))
            lane = _val((yield from ask(prefixed("LANE:"))))
            depth = _num((yield from ask(prefixed("DEPTH:"))))
            return {"space_behind": {"line": line, "lane": lane, "depth": depth}}
        if kind == "best_teammate":
            sc = _val((yield from ask(ids("SC:xt", "SC:pass_p", "SC:pc_xt"))))
            zt = yield from ask(ids("NOZONE", "ZONE_SEL"))
            spec = {"score": sc}
            if zt == TOK["ZONE_SEL"]:
                spec["zone"] = _val((yield from ask(prefixed("Z:"))))
            return {"best_teammate": spec}
        sel = _val((yield from ask(prefixed("SEL:"))))
        return {"opponent": sel}

    # -- predicates ----------------------------------------------------------------------
    def ref():
        t = yield from ask(role_refs | ids("BH", "BALL_REF"))
        name = VOCAB[t]
        return "ball_holder" if name == "BH" else "ball" if name == "BALL_REF" else f"role:{name}"

    def atom(first: int | None = None):
        a = _val(first if first is not None else (yield from ask(prefixed("P:"))))
        if a == "has_ball":
            return {"has_ball": (yield from role_ref())}
        if a == "possession_us":
            return {"possession": "us"}
        if a == "possession_them":
            return {"possession": "them"}
        if a == "event":
            return {"event": _val((yield from ask(prefixed("EV:"))))}
        if a == "step_elapsed_gt":
            return {"step_elapsed_s": {"gt": _num((yield from ask(prefixed("EL:"))))}}
        if a == "ball_in_zone":
            return {"ball_in_zone": _val((yield from ask(prefixed("Z:"))))}
        if a in ("pressure_lt", "pressure_gt"):
            r = yield from ref()
            d = _num((yield from ask(prefixed("D:"))))
            return {"pressure_on": {"ref": r, a[-2:]: d}}
        if a == "lane_open":
            t = yield from ask(role_refs | ids("BH"))
            frm = "ball_holder" if t == TOK["BH"] else VOCAB[t]
            to = yield from target()
            p = _num((yield from ask(prefixed("PR:"))))
            return {"lane_open": {"from": frm, "to": to, "min_p": p}}
        if a == "pc_at_gt":
            to = yield from target()
            return {"pc_at": {"target": to, "gt": _num((yield from ask(prefixed("PR:"))))}}
        if a == "xg_gt":
            r = yield from ref()
            return {"xg": {"ref": r, "gt": _num((yield from ask(prefixed("XG:"))))}}
        if a == "ahead_of":
            r1 = yield from ref()
            r2 = yield from ref()
            return {"ahead_of": {"a": r1, "b": r2, "by": _num((yield from ask(prefixed("D:"))))}}
        if a == "dist_lt":
            r1 = yield from ref()
            t = yield from ask(role_refs | ids("BH", "BALL_REF") | prefixed("A:"))
            name = VOCAB[t]
            r2 = ("ball_holder" if name == "BH" else "ball" if name == "BALL_REF" else
                  f"anchor:{name[2:]}" if name.startswith("A:") else f"role:{name}")
            return {"dist": {"a": r1, "b": r2, "lt": _num((yield from ask(prefixed("D:"))))}}
        if a == "onside":
            return {"onside": (yield from role_ref())}
        return {"ball_beyond_line": {"line": _val((yield from ask(prefixed("LINE:"))))}}

    def pred(reserve: int = 0):
        opts = {TOK["ALWAYS"]}
        if b.allow(reserve + R_ATOM):
            opts |= set(prefixed("P:"))
        if b.allow(reserve + R_PRED):
            opts |= {TOK["ALL"], TOK["ANY"], TOK["NOT"]}
        t = yield from ask(frozenset(opts))
        if t == TOK["ALWAYS"]:
            return "always"
        if t == TOK["NOT"]:
            return {"not": (yield from atom())}
        if t in (TOK["ALL"], TOK["ANY"]):
            items = []
            while True:
                opts = set()
                if len(items) < MAX_ATOMS and b.allow(reserve + R_ATOM + 1):
                    opts |= set(prefixed("P:"))
                if items:
                    opts.add(TOK["END_GROUP"])
                if not opts:
                    opts = set(prefixed("P:"))
                a = yield from ask(frozenset(opts))
                if a == TOK["END_GROUP"]:
                    break
                items.append((yield from atom(a)))
            return {("all" if t == TOK["ALL"] else "any"): items}
        return (yield from atom(t))

    # -- actions ---------------------------------------------------------------------------
    def action():
        t = yield from ask(role_refs | ids("BH"))
        actor = {"actor": "ball_holder"} if t == TOK["BH"] else {"role": VOCAB[t]}
        atype = _val((yield from ask(prefixed("TYPE:"))))
        p: dict[str, Any] = {}
        if atype == "pass":
            p["to"] = yield from target()
            p["style"] = _val((yield from ask(prefixed("PS:"))))
            if (yield from ask(ids("OT0", "OT1"))) == TOK["OT1"]:
                p["one_touch"] = True
        elif atype == "cross":
            p["to"] = yield from target()
            p["style"] = _val((yield from ask(prefixed("CS:"))))
        elif atype in ("cutback", "dribble", "third_man_run", "decoy_run", "hold_position"):
            p["to"] = yield from target()
        elif atype == "carry":
            p["to"] = yield from target()
            p["speed"] = _val((yield from ask(prefixed("SPD:"))))
        elif atype == "shoot":
            p["placement"] = _val((yield from ask(prefixed("PL:"))))
        elif atype == "hold_up":
            p["duration_s"] = _num((yield from ask(prefixed("DUR:"))))
        elif atype == "run_to":
            p["to"] = yield from target()
            p["speed"] = _val((yield from ask(prefixed("SPD:"))))
            if (yield from ask(ids("NOARRIVE", "ARRIVE"))) == TOK["ARRIVE"]:
                p["arrive_with"] = yield from role_ref()
        elif atype in ("overlap", "underlap"):
            p["around"] = yield from role_ref()
        elif atype == "spin_in_behind":
            p["line"] = _val((yield from ask(prefixed("LINE:"))))
            p["lane"] = _val((yield from ask(prefixed("LANE:"))))
            p["depth"] = _num((yield from ask(prefixed("DEPTH:"))))
        elif atype == "check_to_ball":
            p["distance"] = _num((yield from ask(prefixed("D:"))))
            p["duration_s"] = _num((yield from ask(prefixed("DUR:"))))
        elif atype == "support":
            p["from"] = yield from role_ref()
            p["angle"] = _val((yield from ask(prefixed("ANG:"))))
            p["distance"] = _num((yield from ask(prefixed("D:"))))
        elif atype == "hold_width":
            p["lane"] = _val((yield from ask(prefixed("LANE:"))))
        return {**actor, "type": atype, **p}

    def action_list(reserve: int):
        acts = []
        while True:
            opts = set()
            if len(acts) < MAX_ACTIONS and b.allow(reserve + R_ACT):
                opts.add(TOK["ACT"])
            if acts:
                opts.add(TOK["END_ACTS"])
            if not opts:
                opts = {TOK["ACT"]}
            t = yield from ask(frozenset(opts))
            if t == TOK["END_ACTS"]:
                return acts
            acts.append((yield from action()))

    # -- steps -------------------------------------------------------------------------------
    steps: list[dict] = []
    while True:
        opts = set()
        if len(steps) < MAX_STEPS and b.allow(STEP_MIN + R_TAIL_MIN):
            opts.add(TOK["STEP"])
        if steps:
            opts.add(TOK["END_STEPS"])
        if not opts:
            opts = {TOK["END_STEPS"]}
        t = yield from ask(frozenset(opts))
        if t == TOK["END_STEPS"]:
            break
        step: dict[str, Any] = {"id": f"s{len(steps) + 1}"}
        reserve = 4 + R_TAIL_MIN   # DONE <pred> TO after the actions, then the play's tail
        if (yield from ask(ids("START", "NOSTART"))) == TOK["START"]:
            step["start_when"] = yield from pred(REST_OF_STEP + R_TAIL_MIN)
        kind = yield from ask(ids("ACTS", "CHOOSE") if b.allow(reserve + 2 * R_ACT + R_PRED + 4) else ids("ACTS"))
        if kind == TOK["ACTS"]:
            step["actions"] = yield from action_list(reserve)
        else:
            options = []
            while True:
                opts = {TOK["ELSE"]}
                if len(options) < MAX_OPTIONS - 1 and b.allow(reserve + R_PRED + 2 * R_ACT + 4):
                    opts.add(TOK["WHEN"])
                t = yield from ask(frozenset(opts))
                if t == TOK["ELSE"]:
                    options.append({"when": "always", "actions": (yield from action_list(reserve))})
                    break
                w = yield from pred(reserve + 2 * R_ACT)
                options.append({"when": w, "actions": (yield from action_list(reserve + R_ACT))})
            step["choose"] = options
        yield from ask(ids("DONE"))
        step["done_when"] = yield from pred(1 + R_TAIL_MIN)
        step["timeout_s"] = _num((yield from ask(prefixed("TO:"))))
        step["on_timeout"] = "abort"
        steps.append(step)

    yield from ask(ids("SUCCESS"))
    success = yield from pred(3)
    yield from ask(ids("ABORT"))
    abort = yield from pred(1)
    yield from ask(ids("<eos>"))

    total = sum(s["timeout_s"] for s in steps)
    trig: list[Any] = [{"possession": "us"}, {"has_ball": "R1"}]
    if phase == "transition_attack":
        trig.append({"event": {"type": "possession_won", "within_s": 2.0}})
    return {
        "name": "Generated play", "phase": phase, "objective": objective, "strategy": "generated",
        "roles": roles, "triggers": {"all": trig}, "steps": steps, "success": success,
        "abort": abort if abort != "always" else {"any": []},
        "max_duration_s": round(total + 2.0, 2), "cooldown_s": 0.0,
        "soft_hints": {"risk": risk, "chain_depth": len(steps), "tempo": tempo},
        "source": "generated",
    }


def play_id_for(tokens: list[int]) -> str:
    """Generated plays are named by a hash of their tokens (spec §10.3)."""
    return "gen_" + hashlib.sha1(bytes(str(tokens), "utf8")).hexdigest()[:10]


def detokenize(tokens: list[int], max_len: int = 320) -> dict[str, Any]:
    """Run the grammar over a token sequence; raise ``ValueError`` if it is off-grammar."""
    prog = play_program(max_len)
    allowed = next(prog)
    try:
        for t in tokens:
            if t not in allowed:
                raise ValueError(f"token {VOCAB[t]!r} at this position is not allowed by the grammar")
            allowed = prog.send(t)
    except StopIteration as stop:
        play = stop.value
        play["id"] = play_id_for(tokens)
        return play
    raise ValueError("token sequence ended before the play was complete")
