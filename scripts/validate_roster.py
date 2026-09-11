"""Validate a roster file and report what your squad can and cannot field.

Run this after editing ``data/rosters/home.json``. It answers three questions:

1. **Is the file valid?** Unknown keys, unknown slots or roles, duplicate ids and
   out-of-scale values all fail here with a message naming the player.
2. **Which play roles can the squad fill, and how deep?** A role with depth 1 is a
   single point of failure: covered today, but one card or one tired player makes every
   play requiring it infeasible at once (§5's ``min_role_coverage``).
3. **For an uncovered role, who came closest and by how much?** "Nobody can do this" is
   not actionable; "your quickest forward is 0.1 m/s short" is.

Usage::

    python scripts/validate_roster.py                    # default roster
    python scripts/validate_roster.py --matrix           # full player x role fit grid
    python scripts/validate_roster.py path/to/other.json

Exits non-zero if the file is invalid or any catalogue role is uncovered, so it works
as a pre-commit or CI check.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from soccersim.constraints.roles import squad_coverage  # noqa: E402
from soccersim.domain.entities import Team  # noqa: E402
from soccersim.domain.pitch import vec  # noqa: E402
from soccersim.domain.roles import ROLE_CATALOGUE, role_fit  # noqa: E402
from soccersim.domain.roster import DEFAULT_ROSTER_PATH, RosterError, load_roster  # noqa: E402


def print_matrix(players) -> None:
    """Full fit grid. `*` marks a practised role, `-` a failed minimum."""
    keys = sorted(ROLE_CATALOGUE)
    width = max(len(k) for k in keys) + 2
    print("\nFit matrix — '*' practised, '-' below minimum or wrong slot\n")
    header = "role".ljust(width) + "".join(f"{p.player_id:>7}" for p in players)
    print(header)
    print("-" * len(header))
    for key in keys:
        row = key.ljust(width)
        for player in players:
            fit = role_fit(player, ROLE_CATALOGUE[key])
            mark = "*" if fit.practised else " "
            cell = "   -  " if not fit.meets_minimums else f"{fit.score:.3f} "
            row += f"{cell}{mark}"
        print(row)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "path", nargs="?", type=pathlib.Path, default=DEFAULT_ROSTER_PATH
    )
    parser.add_argument("--matrix", action="store_true", help="print the full fit grid")
    args = parser.parse_args()

    try:
        roster = load_roster(args.path)
    except RosterError as error:
        print(f"INVALID: {error}", file=sys.stderr)
        return 1

    print(roster.summary())

    if roster.defaulted_attributes:
        print("\nAttributes absent from the file, defaulted to 50:")
        for player_id, names in sorted(roster.defaulted_attributes.items()):
            print(f"  player {player_id}: {', '.join(names)}")
        print("  (a defaulted 50 looks identical to an authored one in every fit score)")

    players = [entry.to_player_state(Team.HOME, vec(0.0, 0.0)) for entry in roster]
    coverage = squad_coverage(players)

    print(f"\nRole coverage — {len(coverage)} catalogue roles\n")
    print(f"{'role':<24}{'depth':>6}  {'best fit':<22}{'practised?':<12}")
    print("-" * 66)
    uncovered, thin = [], []
    for key, cover in coverage.items():
        best = cover.best
        if best is None:
            uncovered.append(key)
            print(f"{key:<24}{0:>6}  {'UNCOVERED':<22}{'':<12}")
            continue
        if cover.depth == 1:
            thin.append(key)
        entry = roster.entry(best.player_id)
        label = f"{entry.name or best.player_id} ({best.score:.3f})"
        print(
            f"{key:<24}{cover.depth:>6}  {label:<22}"
            f"{'yes' if best.practised else 'NO':<12}"
        )

    for key in uncovered:
        closest = coverage[key].closest_miss()
        if closest is None:
            print(f"\n{key}: uncovered, and no player is even close on the gated attributes.")
            continue
        shortfalls = ", ".join(
            f"{name} {actual:g} (needs {required:g})"
            for name, (actual, required) in sorted(closest.unmet.items())
        )
        print(f"\n{key}: uncovered. Closest is player {closest.player_id} — {shortfalls}")

    if thin:
        print(
            f"\nDepth 1 (one absence makes every play needing these infeasible): "
            f"{', '.join(thin)}"
        )

    unpractised = [
        key
        for key, cover in coverage.items()
        if cover.best is not None and not cover.best.practised
    ]
    if unpractised:
        print(
            "\nBest fit has not practised the role (feeds §5's role_familiarity "
            f"penalty): {', '.join(unpractised)}"
        )

    if uncovered:
        print(f"\n{len(uncovered)} role(s) uncovered.", file=sys.stderr)
        return 1
    print("\nOK — every catalogue role is coverable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
