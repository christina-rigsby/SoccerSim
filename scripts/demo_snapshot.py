"""Render the M0 space layer for each canonical fixture.

Writes one PNG per fixture to ``out/``. Looking at these is the real verification for
the space layer (D-011) — the numeric tests catch regressions, the images catch
"the geometry is subtly wrong".

What to check in each image:

- **Control field** — blue is home's space, red away's. Each team should own the ground
  in front of and around its players. Players moving fast should own space *ahead* of
  themselves, not centred on their feet; that is the whole point of using arrival time
  rather than distance (D-013).
- **Passing lanes** — solid green open, dashed red blocked with an ``x`` at the tightest
  point of the ball-vs-defender race.
- **Cover shadows** — the pale red wedges must sit *behind* each defender as seen from
  the ball, and must swing round as the ball moves.
- **Threat contours** — purple lines should tighten toward the goal being attacked.

Usage::

    python scripts/demo_snapshot.py [--resolution 1.5] [--outdir out]
"""

from __future__ import annotations

import argparse
import pathlib
import sys

import matplotlib

matplotlib.use("Agg")

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from soccersim.domain.entities import Team  # noqa: E402
from soccersim.domain.fixtures import ALL_FIXTURES  # noqa: E402
from soccersim.space.grid import PitchGrid  # noqa: E402
from soccersim.space.passing_lanes import open_lanes  # noqa: E402
from soccersim.space.pitch_control import control_field  # noqa: E402
from soccersim.space.xt import AnalyticThreatSurface  # noqa: E402
from soccersim.viz.render import save_state  # noqa: E402


def render_fixture(name: str, state, resolution: float, outdir: pathlib.Path) -> pathlib.Path:
    grid = PitchGrid(state.pitch, resolution)
    control = control_field(state, Team.HOME, grid)
    threat = AnalyticThreatSurface(state.pitch).field(grid, state.home.attacking_direction)

    # Lanes from wherever the ball is, to every home player who is not carrying it.
    carrier = state.ball.carrier_id
    lanes = [
        assessment
        for _, assessment in open_lanes(
            state,
            state.ball.position,
            Team.HOME,
            exclude=() if carrier is None else (carrier,),
        )
    ]

    open_count = sum(1 for lane in lanes if lane.is_open)
    shape = state.home.shape()
    print(
        f"{name:16} control(home)={control.controlled_area() / 1e3:5.1f}k m^2  "
        f"lanes open={open_count}/{len(lanes)}  "
        f"home width={shape['width']:.0f}m depth={shape['depth']:.0f}m"
    )

    path = outdir / f"{name}.png"
    save_state(
        str(path),
        state,
        control=control,
        threat=threat,
        threat_grid=grid,
        lanes=lanes,
        shadows_for=Team.HOME,
        title=(
            f"{name.replace('_', ' ')} — home pitch control, "
            f"passing lanes from the ball, away cover shadows"
        ),
    )
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--resolution", type=float, default=1.5, help="grid cell size in metres"
    )
    parser.add_argument("--outdir", type=pathlib.Path, default=pathlib.Path("out"))
    parser.add_argument(
        "--fixture",
        choices=sorted(ALL_FIXTURES),
        help="render only this fixture (default: all)",
    )
    args = parser.parse_args()

    args.outdir.mkdir(parents=True, exist_ok=True)
    names = [args.fixture] if args.fixture else sorted(ALL_FIXTURES)

    for name in names:
        path = render_fixture(name, ALL_FIXTURES[name](), args.resolution, args.outdir)
        print(f"{'':16} -> {path}")


if __name__ == "__main__":
    main()
