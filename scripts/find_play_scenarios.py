"""Find and pin, for every library play, a seed + scenario where Module 2 instantiates it.

Writes ``tests/fixtures/play_scenarios.json``, which the execution tests (spec §6.13)
replay deterministically. Re-run after changing the simulator or the play library.
"""

from __future__ import annotations

import json
from pathlib import Path

from soccersim.schema import load_library
from soccersim.sim.play_scenarios import find_play_scenario

OUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "play_scenarios.json"


def main() -> int:
    lib = load_library()
    pinned, missing = {}, []
    for pid in sorted(lib):
        run = find_play_scenario(lib, pid)
        if run is None:
            missing.append(pid)
            print(f"{pid:32s} NOT FOUND")
            continue
        rec = run.forced_record(pid)
        pinned[pid] = {"seed": run.seed, "scenario": run.scenario.to_dict(), "end_reason": rec["end_reason"]}
        print(f"{pid:32s} seed={run.seed:3d} {run.scenario.type:20s} -> {rec['end_reason']} {rec['steps_visited']}")
    OUT.write_text(json.dumps(pinned, indent=2) + "\n")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
