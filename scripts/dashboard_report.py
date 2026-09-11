"""Run a scripted scenario through the dashboard and print what it inferred.

The counterpart to ``demo_snapshot.py``: that one verifies the space layer by eye, this
one verifies the opponent model by checking recovered estimates against the ground truth
each scenario was built with.

Usage::

    python scripts/dashboard_report.py                 # every scenario, scored
    python scripts/dashboard_report.py man_marking     # one, in full
    python scripts/dashboard_report.py --full          # full reports for all

Exits non-zero if any estimator fails to recover its scenario's planted behaviour, so it
works as a regression check on the inference itself rather than only on the code.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from soccersim.dashboard import Dashboard  # noqa: E402
from soccersim.domain.entities import Team  # noqa: E402
from soccersim.scenarios import ALL_SCENARIOS, Scenario  # noqa: E402


def score(scenario: Scenario, dashboard: Dashboard) -> list[str]:
    """Compare recovered estimates against the planted truth. Returns failures."""
    failures: list[str] = []
    model = dashboard.opponent_model()
    truth = scenario.truth

    if truth.marking_scheme is not None:
        got = model.marking_scheme
        if not got.is_mature:
            failures.append(
                f"marking scheme never matured ({got.observations:.0f} obs)"
            )
        elif got.value is not truth.marking_scheme:
            failures.append(
                f"marking scheme: expected {truth.marking_scheme.value}, "
                f"got {got.value.value}"
            )

    if truth.marking_assignments:
        recovered = {
            defender: estimate.value
            for defender, estimate in model.marking_assignments.items()
            if estimate.is_mature
        }
        missing = {
            d: a for d, a in truth.marking_assignments.items() if recovered.get(d) != a
        }
        if missing:
            failures.append(f"assignments not recovered: {missing}")

    recovered_triggers = set(model.press_triggers)
    if recovered_triggers != set(truth.press_triggers):
        failures.append(
            f"triggers: expected {sorted(truth.press_triggers)}, "
            f"got {sorted(recovered_triggers)}"
        )

    for key in truth.press_non_triggers:
        if key in recovered_triggers:
            failures.append(f"negative control {key} was reported as a trigger")

    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", nargs="?", choices=sorted(ALL_SCENARIOS))
    parser.add_argument("--full", action="store_true", help="print the whole report")
    args = parser.parse_args()

    names = [args.scenario] if args.scenario else sorted(ALL_SCENARIOS)
    show_full = args.full or args.scenario is not None
    total_failures = 0

    for name in names:
        scenario = ALL_SCENARIOS[name]()
        dashboard = Dashboard(our_team=Team.HOME)
        dashboard.observe_all(scenario.frames)

        print(f"\n{'=' * 78}\n{name}  —  {scenario.description}")
        print(f"{len(scenario)} frames over {scenario.duration:.1f}s")
        if show_full:
            print()
            print(dashboard.report())

        failures = score(scenario, dashboard)
        total_failures += len(failures)
        if failures:
            print("\nFAILED to recover ground truth:")
            for failure in failures:
                print(f"  - {failure}")
        else:
            print("\nground truth recovered")

    print(f"\n{'=' * 78}")
    if total_failures:
        print(f"{total_failures} estimator failure(s)", file=sys.stderr)
        return 1
    print("All scenarios: every planted behaviour recovered, no false positives.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
