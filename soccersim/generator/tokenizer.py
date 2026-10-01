"""Play -> token sequence under the grammar (spec §10.2).

Library plays use the full schema; the generator speaks a restricted, tokenizable subset.
:func:`tokenize_play` maps a play into that subset — roles renamed ``R1..Rn`` with the
ball role first, offsets snapped to the 2 m grid, numbers binned, unsupported predicates
dropped from their group (an empty group becomes ``always``) — so the conversion is
deliberately lossy. Every output is checked by running it back through the grammar; a
play that cannot be expressed raises :class:`TokenizeError`.
"""

from __future__ import annotations

from typing import Any

from ..schema.models import Play
from .grammar import (
    ACTION_TYPES,
    ANCHORS,
    CROSS_STYLES,
    DEPTH_BINS,
    DIST_BINS,
    DUR_BINS,
    ELAPSED_BINS,
    LEAD_BINS,
    MAX_ACTIONS,
    MAX_ATOMS,
    MAX_OPTIONS,
    MAX_ROLES,
    MAX_STEPS,
    OBJECTIVES,
    PASS_STYLES,
    PHASES,
    PROB_BINS,
    REQ_BINS,
    RISK_BINS,
    SELECTORS,
    STEP_EVENTS,
    TIMEOUT_BINS,
    TOK,
    XG_BINS,
    ZONES,
    detokenize,
)


class TokenizeError(ValueError):
    pass


def _bin(v: float, bins) -> str:
    b = min(bins, key=lambda x: abs(x - float(v)))
    return str(b)


def _off(v: float) -> str:
    return str(int(max(-30, min(30, 2 * round(float(v) / 2)))))


class _Conv:
    def __init__(self, play: Play) -> None:
        self.play = play
        roles = sorted(play.roles, key=lambda r: not r.starts_with_ball)
        if not roles or not roles[0].starts_with_ball:
            raise TokenizeError("possession plays need a ball role")
        if any(r.group for r in roles):
            raise TokenizeError("group roles are not tokenizable")
        self.roles = roles[:MAX_ROLES]
        self.map = {r.id: f"R{i + 1}" for i, r in enumerate(self.roles)}

    def role(self, rid: str) -> str | None:
        return self.map.get(rid)

    # -- refs, targets ---------------------------------------------------------------------
    def ref(self, ref: str) -> list[str] | None:
        if ref == "ball_holder":
            return ["BH"]
        if ref == "ball":
            return ["BALL_REF"]
        if ref.startswith("role:") and self.role(ref[5:]):
            return [self.role(ref[5:])]
        return None

    def target(self, t: dict) -> list[str] | None:
        if "role" in t:
            r = self.role(t["role"])
            return None if r is None else ["T:role", r, f"LEAD:{_bin(t.get('lead', 0), LEAD_BINS)}"]
        if "anchor" in t:
            a = t["anchor"]
            dx, dy = t.get("offset", [0, 0])
            if a in ANCHORS:
                head = [f"A:{a}"]
            elif a.startswith("role:") and self.role(a[5:]):
                head = [self.role(a[5:])]
            elif a.startswith("line:"):
                head = [f"LINE:{a[5:]}"]
            elif a.startswith("opp:nearest_to_role:") and self.role(a.split(":")[2]):
                head = [self.role(a.split(":")[2])]       # approximate: anchor on our player instead
            else:
                head = ["A:ball"]
            fr = "FREEZE" if t.get("freeze") else "LIVE"
            return ["T:anchor", *head, f"OFF:{_off(dx)}", f"OFF:{_off(dy)}", fr]
        if "zone" in t:
            if t["zone"] not in ZONES:
                return None
            return ["T:zone_c" if t.get("pick") == "centroid" else "T:zone", f"Z:{t['zone']}"]
        if "pc_best" in t:
            region = t["pc_best"]
            if "zone" in region and region["zone"] in ZONES:
                return ["T:pc_best", f"Z:{region['zone']}", f"SC:{t.get('score', 'pc')}"]
            return ["T:anchor", "A:ball", "OFF:2", "OFF:0", "LIVE"]
        if "space_behind" in t:
            sb = t["space_behind"]
            return ["T:space_behind", f"LINE:{sb['line']}", f"LANE:{sb['lane']}",
                    f"DEPTH:{_bin(sb['depth'], DEPTH_BINS)}"]
        if "best_teammate" in t:
            bt = t["best_teammate"]
            z = bt.get("zone")
            return ["T:best_teammate", f"SC:{bt['score']}", *(["ZONE_SEL", f"Z:{z}"] if z in ZONES else ["NOZONE"])]
        if "opponent" in t and t["opponent"] in SELECTORS:
            return ["T:opponent", f"SEL:{t['opponent']}"]
        return None

    # -- predicates ---------------------------------------------------------------------------
    def atom(self, p: Any) -> list[str] | None:
        if not isinstance(p, dict) or len(p) != 1:
            return None
        (k, v), = p.items()
        if k == "possession" and v in ("us", "them"):
            return [f"P:possession_{v}"]
        if k == "has_ball" and self.role(v):
            return ["P:has_ball", self.role(v)]
        if k == "event":
            et = v if isinstance(v, str) else v.get("type")
            return ["P:event", f"EV:{et}"] if et in STEP_EVENTS else None
        if k == "step_elapsed_s" and "gt" in v:
            return ["P:step_elapsed_gt", f"EL:{_bin(v['gt'], ELAPSED_BINS)}"]
        if k == "ball_in_zone":
            zs = v if isinstance(v, list) else [v]
            z = next((z for z in zs if z in ZONES), None)
            return None if z is None else ["P:ball_in_zone", f"Z:{z}"]
        if k == "pressure_on":
            r = self.ref(v["ref"])
            if r is None:
                return None
            if "lt" in v:
                return ["P:pressure_lt", *r, f"D:{_bin(v['lt'], DIST_BINS)}"]
            if "gt" in v:
                return ["P:pressure_gt", *r, f"D:{_bin(v['gt'], DIST_BINS)}"]
            return None
        if k == "lane_open":
            frm = ["BH"] if v["from"] == "ball_holder" else ([self.role(v["from"])] if self.role(v["from"]) else None)
            to = self.target(v["to"])
            if frm is None or to is None:
                return None
            return ["P:lane_open", *frm, *to, f"PR:{_bin(v['min_p'], PROB_BINS)}"]
        if k == "pc_at" and "gt" in v:
            to = self.target(v["target"])
            return None if to is None else ["P:pc_at_gt", *to, f"PR:{_bin(v['gt'], PROB_BINS)}"]
        if k == "xg" and "gt" in v:
            r = self.ref(v["ref"])
            return None if r is None else ["P:xg_gt", *r, f"XG:{_bin(v['gt'], XG_BINS)}"]
        if k == "ahead_of":
            a, b = self.ref(v["a"]), self.ref(v["b"])
            return None if a is None or b is None else ["P:ahead_of", *a, *b, f"D:{_bin(v.get('by', 0), DIST_BINS)}"]
        if k == "dist" and "lt" in v:
            a = self.ref(v["a"])
            bref = v["b"]
            b = self.ref(bref)
            if b is None and bref.startswith("anchor:") and bref[7:] in ANCHORS:
                b = [f"A:{bref[7:]}"]
            return None if a is None or b is None else ["P:dist_lt", *a, *b, f"D:{_bin(v['lt'], DIST_BINS)}"]
        if k == "onside" and self.role(v):
            return ["P:onside", self.role(v)]
        if k == "ball_beyond_line":
            return ["P:ball_beyond", f"LINE:{v['line']}"]
        return None

    def pred(self, p: Any) -> list[str]:
        if p == "always":
            return ["ALWAYS"]
        if isinstance(p, dict) and len(p) == 1:
            (k, v), = p.items()
            if k in ("all", "any"):
                atoms = [a for a in (self.atom(x) for x in v) if a is not None][:MAX_ATOMS]
                if not atoms:
                    return ["ALWAYS"] if k == "all" else ["ALWAYS"]
                if len(atoms) == 1:
                    return atoms[0]
                return ["ALL" if k == "all" else "ANY", *[t for a in atoms for t in a], "END_GROUP"]
            if k == "not":
                a = self.atom(v)
                return ["NOT", *a] if a is not None else ["ALWAYS"]
        a = self.atom(p)
        return a if a is not None else ["ALWAYS"]

    # -- actions ---------------------------------------------------------------------------------
    def action(self, a) -> list[str] | None:
        t = a.type
        params = a.params
        if t == "distribute":
            t = "pass"
        if t not in ACTION_TYPES:
            return None
        if a.role is not None:
            actor = self.role(a.role)
            if actor is None:
                return None
        elif a.actor == "ball_holder":
            actor = "BH"
        else:
            return None
        out = [actor, f"TYPE:{t}"]

        def tgt(key="to"):
            v = self.target(params[key]) if key in params else None
            return v

        if t in ("pass", "cross", "cutback", "carry", "dribble", "run_to", "third_man_run", "decoy_run",
                 "hold_position"):
            to = tgt()
            if to is None:
                return None
            out += to
        if t == "pass":
            st = params.get("style", "ground")
            out += [f"PS:{st if st in PASS_STYLES else 'ground'}", "OT1" if params.get("one_touch") else "OT0"]
        elif t == "cross":
            st = params.get("style", "lofted")
            out += [f"CS:{st if st in CROSS_STYLES else 'lofted'}"]
        elif t == "carry":
            out += [f"SPD:{params.get('speed', 'fast')}"]
        elif t == "shoot":
            out += [f"PL:{params.get('placement', 'auto')}"]
        elif t == "hold_up":
            out += [f"DUR:{_bin(params['duration_s'], DUR_BINS)}"]
        elif t == "run_to":
            out += [f"SPD:{params.get('speed', 'fast')}"]
            aw = self.role(params.get("arrive_with", "")) if params.get("arrive_with") else None
            out += ["ARRIVE", aw] if aw else ["NOARRIVE"]
        elif t in ("overlap", "underlap"):
            r = self.role(params["around"])
            if r is None:
                return None
            out += [r]
        elif t == "spin_in_behind":
            out += [f"LINE:{params['line']}", f"LANE:{params['lane']}", f"DEPTH:{_bin(params['depth'], DEPTH_BINS)}"]
        elif t == "check_to_ball":
            out += [f"D:{_bin(params['distance'], DIST_BINS)}", f"DUR:{_bin(params['duration_s'], DUR_BINS)}"]
        elif t == "support":
            r = self.role(params["from"])
            if r is None:
                return None
            out += [r, f"ANG:{params['angle']}", f"D:{_bin(params['distance'], DIST_BINS)}"]
        elif t == "hold_width":
            out += [f"LANE:{params['lane']}"]
        return ["ACT", *out]

    def actions(self, acts) -> list[str]:
        toks = [a for a in (self.action(x) for x in acts) if a is not None][:MAX_ACTIONS]
        if not toks:
            toks = [["ACT", "R1", "TYPE:hold_up", "DUR:0.5"]]
        return [t for a in toks for t in a] + ["END_ACTS"]

    def tokens(self) -> list[str]:
        p = self.play
        if p.phase not in PHASES:
            raise TokenizeError(f"phase {p.phase} is not generated")
        obj = p.objective if p.objective in OBJECTIVES else "progress_ball"
        out = ["<bos>", f"PHASE:{p.phase}", f"OBJ:{obj}", f"TEMPO:{p.soft_hints.tempo}",
               f"RISK:{_bin(p.soft_hints.risk, RISK_BINS)}"]
        for r in self.roles:
            out.append("ROLE")
            hints = list(dict.fromkeys(r.hints))[:3] or ["CM"]
            out += [f"HINT:{h}" for h in hints] + ["END_HINTS"]
            for cap, v in list(r.requires.items())[:2]:
                out += [f"REQ:{cap}", f"RBIN:{_bin(v, REQ_BINS)}"]
            out.append("END_REQ")
        out.append("END_ROLES")
        for s in p.steps[:MAX_STEPS]:
            out.append("STEP")
            out += ["START", *self.pred(s.start_when)] if s.start_when is not None else ["NOSTART"]
            if s.actions is not None:
                out += ["ACTS", *self.actions(s.actions)]
            else:
                out.append("CHOOSE")
                opts = list(s.choose)
                conds = [o for o in opts if o.when != "always"][:MAX_OPTIONS - 1]
                default = next((o for o in opts if o.when == "always"), opts[-1])
                for o in conds:
                    if o is default:
                        continue
                    out += ["WHEN", *self.pred(o.when), *self.actions(o.actions)]
                out += ["ELSE", *self.actions(default.actions)]
            out += ["DONE", *self.pred(s.done_when), f"TO:{_bin(s.timeout_s or 3.0, TIMEOUT_BINS)}"]
        out += ["END_STEPS", "SUCCESS", *self.pred(p.success), "ABORT", *self.pred(p.abort), "<eos>"]
        return out


def tokenize_play(play: Play, max_len: int = 320) -> list[int]:
    names = _Conv(play).tokens()
    try:
        toks = [TOK[n] for n in names]
    except KeyError as e:
        raise TokenizeError(f"{play.id}: no token {e}") from None
    try:
        detokenize(toks, max_len)
    except ValueError as e:
        raise TokenizeError(f"{play.id}: {e}") from None
    return toks


def tokenize_library(library: dict[str, Play]) -> dict[str, list[int]]:
    out = {}
    for pid, play in library.items():
        try:
            out[pid] = tokenize_play(play)
        except TokenizeError:
            continue
    return out
