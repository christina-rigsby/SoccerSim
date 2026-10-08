"""Write docs/ACTIONS.md: every action a play can use, from the code itself.

    python scripts/action_reference.py

Parameters come from ``soccersim/schema/vocab.py: ACTION_SPECS`` (what the validator accepts),
the implementing function and its location from the controller registry
(``soccersim/controllers/``), and which actions the generator may write from its grammar.
Only the one-line meanings below are written by hand; the script fails if an action has no
meaning, no controller, or a controller has no action, so the document cannot drift.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import soccersim.controllers.defensive  # noqa: E402,F401  (registers controllers)
import soccersim.controllers.off_ball  # noqa: E402,F401
import soccersim.controllers.on_ball  # noqa: E402,F401
import soccersim.controllers.shape  # noqa: E402,F401
from soccersim.controllers.base import REGISTRY  # noqa: E402
from soccersim.schema.vocab import ACTION_SPECS  # noqa: E402

OUT = ROOT / "docs" / "ACTIONS.md"

CATEGORY = {
    **dict.fromkeys(("pass", "cross", "cutback", "carry", "dribble", "shoot", "hold_up", "clear", "distribute"),
                    "on-ball"),
    **dict.fromkeys(("run_to", "overlap", "underlap", "third_man_run", "spin_in_behind", "check_to_ball", "decoy_run",
                     "support", "hold_width", "hold_position"), "off-ball"),
    **dict.fromkeys(("press", "cover", "mark", "block_lane", "block_shot", "jockey", "tackle", "recover",
                     "compact_shift", "hold_line"), "defensive"),
    "set_position": "keeper",
}

MEANING = {
    "pass": "Pass to a target (a role, a point or the best teammate). Waits 0.3 s after receiving unless "
            "`one_touch`. The pass itself (speed, interception) is simulated by the pass model.",
    "cross": "A pass from wide into the box; default style lofted.",
    "cutback": "A one-touch ground pass back from the byline area.",
    "carry": "Run with the ball to a target; `protect` shields it at reduced speed. Done on arrival.",
    "dribble": "Carry towards a target, steering round the defender in the way (or the one named in `beat`).",
    "shoot": "Shoot at goal; `placement` near/far/auto and `style` placed/power feed the shot model.",
    "hold_up": "Keep the ball, shielding it, for `duration_s` seconds.",
    "clear": "One-touch clearance to a target, or long and wide if none is given.",
    "distribute": "Goalkeeper pass (same mechanics as `pass`).",
    "run_to": "Run to a target. `arrive_with` times the run to meet the named role's delivery.",
    "overlap": "Run round the outside of a teammate, then on to the target (default 10 m ahead, outside).",
    "underlap": "As `overlap`, but round the inside.",
    "third_man_run": "Run to a target to receive a pass via a third player (moves like `run_to`).",
    "spin_in_behind": "Hold onside along the given line until our pass is played, then run into the space behind.",
    "check_to_ball": "Come short towards the ball by up to `distance` metres for `duration_s` seconds.",
    "decoy_run": "A run to drag a defender away (moves like `run_to`; nobody passes to it by design).",
    "support": "Take up a supporting position relative to a teammate at the given angle and distance.",
    "hold_width": "Stay wide in a lane, level with the ball and onside.",
    "hold_position": "Go to a target and stay there.",
    "press": "Close down an opponent; `curve` approaches from one side to force play inside or outside; "
             "`intensity` sets the speed.",
    "cover": "Sit `depth` metres goal-side of a teammate to cover if they are beaten.",
    "mark": "Stay `tightness` metres from an opponent, goal-side (or ball-side).",
    "block_lane": "Stand in the passing lane between two opponents.",
    "block_shot": "Step 3 m goal-side of the ball to block a shot.",
    "jockey": "Stay 2.5 m goal-side of the ball carrier without diving in.",
    "tackle": "Go straight at an opponent and try to win the ball.",
    "recover": "Sprint back to a target (default: behind the ball, towards our goal).",
    "compact_shift": "Group action: hold a line at `line_height` metres from our goal, `width` wide, shifted "
                     "towards the ball by `ball_shift`.",
    "hold_line": "Group action: hold a line at `height`; step up 10 m when the `step_up_on` event happens.",
    "set_position": "Goalkeeper: stay near the line (`cover_line`) or further out to sweep (`sweep`).",
}


def _generator_actions() -> set[str]:
    src = (ROOT / "soccersim" / "generator" / "grammar.py").read_text()
    return {a for a in ACTION_SPECS if f'"{a}"' in src}


def _params(spec: dict) -> str:
    out = []
    for name, (kind, required) in spec.items():
        k = " \\| ".join(kind) if isinstance(kind, tuple) else kind
        out.append(f"`{name}`{'' if required else '?'}: {k}")
    return "<br>".join(out) or "—"


def main() -> int:
    acts = set(ACTION_SPECS)
    problems = sorted(acts - set(MEANING)) + sorted(acts - set(REGISTRY)) + sorted(set(REGISTRY) - acts)
    if problems:
        print("out of sync:", problems)
        return 1
    gen = _generator_actions()
    lines = [
        "# Actions",
        "",
        "Every action a play step can contain (spec §4.4). Generated by `scripts/action_reference.py` from the code;",
        "edit the code (or the one-line meanings in that script), not this file.",
        "",
        "Where an action lives:",
        "",
        "- **Allowed names and parameters:** `soccersim/schema/vocab.py` (`ACTION_SPECS`). The play validator",
        "  (`soccersim/schema/validate.py`) rejects any other action or parameter.",
        "- **What it does in the simulator:** a controller function in `soccersim/controllers/` (registered with",
        "  `@controller(...)`), which turns the action into a steering target, speed and, for on-ball actions, a",
        "  ball command, every tick.",
        "- **When it runs:** the play executor `soccersim/executor/instance.py` walks the play's steps and calls",
        "  each bound player's controller; players not in the play hold their formation shape",
        "  (`soccersim/controllers/shape.py`).",
        "- **Targets** (`to`, `target`: roles, anchors, zones, best pitch-control point, best teammate, space",
        "  behind a line) are resolved by `soccersim/dashboard/evaluator.py` (`Evaluator.target`).",
        "",
        "In a play file an action is `{role: R1, type: pass, to: {role: R2}, style: ground}` or, for a dynamic",
        "actor, `{actor: ball_holder, type: carry, ...}`. `?` marks an optional parameter. \"Generator\" says",
        "whether the play generator's grammar (`soccersim/generator/grammar.py`) can write the action.",
        "",
        "| Action | Category | Parameters | What it does | Controller | Generator |",
        "|---|---|---|---|---|---|",
    ]
    order = ("on-ball", "off-ball", "defensive", "keeper")
    for a in sorted(acts, key=lambda x: (order.index(CATEGORY[x]), x)):
        fn = REGISTRY[a]
        path = Path(inspect.getsourcefile(fn)).resolve().relative_to(ROOT)
        line = inspect.getsourcelines(fn)[1]
        lines.append(f"| `{a}` | {CATEGORY[a]} | {_params(ACTION_SPECS[a])} | {MEANING[a]} | "
                     f"[`{fn.__name__}`](../{path}#L{line}) `{path}:{line}` | {'yes' if a in gen else 'no'} |")
    OUT.write_text("\n".join(lines) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)} ({len(acts)} actions)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
