"""Validate the play library and report how each play behaves against the fixtures.

Three questions, in order:

1. **Is every play file structurally valid?** Unknown anchors, unknown triggers,
   dependency cycles, unknown roles or actions, and §5's ``single_ball`` conflicts all
   fail here.
2. **Does it instantiate?** Resolve every anchor against a fixture and run the hard
   constraints. An infeasible play is a *result*, not a failure — "this play does not fit
   this situation" is what a pre-filter is for.
3. **Does it run?** Rehearse it forward so every trigger actually fires
   (``soccersim.plays.rehearsal``, which is scaffolding, not the simulator).

Usage::

    python scripts/validate_plays.py                     # structure + all fixtures
    python scripts/validate_plays.py --play overlap_right --render
    python scripts/validate_plays.py --fixture opponent_buildup

Exits non-zero only on *structural* invalidity, since infeasibility is legitimate.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from soccersim.domain.entities import Team  # noqa: E402
from soccersim.domain.fixtures import ALL_FIXTURES  # noqa: E402
from soccersim.plays import (  # noqa: E402
    PlayError,
    greedy_assignment,
    instantiate,
    load_library,
)
from soccersim.plays.rehearsal import rehearse  # noqa: E402


def render(instantiated, name: str, outdir: pathlib.Path) -> pathlib.Path:
    import matplotlib

    matplotlib.use("Agg")
    from soccersim.space.grid import PitchGrid
    from soccersim.space.pitch_control import control_field
    from soccersim.viz.render import save_state

    state = instantiated.context.state
    grid = PitchGrid(state.pitch, 1.5)
    path = outdir / f"play_{name}.png"
    save_state(
        str(path),
        state,
        control=control_field(state, instantiated.context.team, grid),
        play=instantiated,
        title=(
            f"{instantiated.play.label} — solid arrows are player runs, "
            f"dashed are ball deliveries"
        ),
    )
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--play", help="only this play")
    parser.add_argument("--fixture", choices=sorted(ALL_FIXTURES), help="only this fixture")
    parser.add_argument("--render", action="store_true", help="write PNGs to out/")
    parser.add_argument("--outdir", type=pathlib.Path, default=pathlib.Path("out"))
    args = parser.parse_args()

    try:
        library = load_library()
    except PlayError as error:
        print(f"INVALID LIBRARY: {error}", file=sys.stderr)
        return 1

    plays = [library.get(args.play)] if args.play else sorted(library, key=lambda p: p.key)
    fixtures = [args.fixture] if args.fixture else sorted(ALL_FIXTURES)

    print(library.summary())

    structural = 0
    for play in plays:
        conflicts = play.concurrent_on_ball()
        if conflicts:
            structural += 1
            print(f"\n{play.key}: SINGLE_BALL CONFLICTS {conflicts}", file=sys.stderr)

    if args.render:
        args.outdir.mkdir(parents=True, exist_ok=True)

    for play in plays:
        print(f"\n{'=' * 78}\n{play.describe()}")
        for fixture_name in fixtures:
            state = ALL_FIXTURES[fixture_name]()
            result = greedy_assignment(play, state, Team.HOME)
            if not result.complete:
                detail = f"unfilled {', '.join(result.unfilled)}"
                if result.starved:
                    detail += f" (starved: {', '.join(result.starved)})"
                print(f"  {fixture_name:<18} no assignment — {detail}")
                continue

            instantiated = instantiate(play, state, result.assignment, Team.HOME)
            violations = instantiated.violations()
            verdict = "feasible" if not violations else f"{len(violations)} violation(s)"
            rehearsal = rehearse(
                play, state, result.assignment, Team.HOME, max_seconds=25.0
            )
            outcome = rehearsal.execution.status.value
            if rehearsal.execution.abort_reason:
                outcome += f" ({rehearsal.execution.abort_reason})"
            print(
                f"  {fixture_name:<18} {verdict:<18} rehearsal: {outcome}"
                f"  [{len(rehearsal.execution.completed_steps)}/{len(play.steps)} steps]"
            )
            for violation in violations[:3]:
                print(f"  {'':<18}   {violation}")

            if args.render and fixture_name == fixtures[0]:
                print(f"  {'':<18}   -> {render(instantiated, play.key, args.outdir)}")

    print(f"\n{'=' * 78}")
    if structural:
        print(f"{structural} play(s) structurally invalid", file=sys.stderr)
        return 1
    print(f"{len(library)} plays structurally valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
