"""Isolated tests of the simulator's laws: one factor at a time, no teams, no plays.

    python scripts/law_tests.py                 # every test, printed as a table
    python scripts/law_tests.py --test pressure --n 600

Each test builds a state with only the players it needs on the pitch (the rest are moved far
away), executes one action with the simulator's own release and ball code, and plays it out
tick by tick until someone controls the ball, it goes out, or time runs out:

- ``pressure``: a ground pass of 20 m from a passer of passing 0.7 to a free receiver, with one
  defender beside the passer at 4 / 2 / 1 m (and none). Reports how often the pass is completed.
  Real football: a pressed pass fails noticeably more often (roughly 5–15 points more).
- ``shots``: a shot from 16 m, central, with 0 / 1 / 3 outfield defenders standing in the line
  between the shooter and the goal. Reports blocked shots and goals per shot. Real football:
  roughly a quarter of shots are blocked, mostly when defenders are in the line.
- ``fatigue``: a fresh player of stamina capability 0.5 doing shuttle runs at full speed, and
  one at half speed; reports top speed (relative to fresh) and fatigue after 1, 5 and 15 minutes.
  Real football: repeated-sprint ability falls by roughly 5–10% over a match.

Writes nothing; the numbers are recorded in docs/REALISM.md.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from soccersim.config import load_config  # noqa: E402
from soccersim.sim.ball import BallCommand, release, step_ball  # noqa: E402
from soccersim.sim.physics import max_speed, step_players  # noqa: E402
from soccersim.sim.scenarios import Scenario, build_state, setup_scenario  # noqa: E402
from soccersim.sim.state import CAP_INDEX  # noqa: E402

DT = 0.1


def _empty_state(cfg: dict, seed: int):
    rng = np.random.default_rng(seed)
    sc = Scenario(type="mid_progression", randomise_capabilities=False)
    st = build_state(rng, sc, cfg)
    setup_scenario(st, sc, rng, cfg)
    st.restart = None
    st.vel[:] = 0.0
    for i in range(22):  # everyone out of the way along the far touchline, each team near its own goal
        st.pos[i] = np.array([-48.0 + 0.8 * i if i < 11 else 40.0 + 0.8 * (i - 11), 33.0])
    st.touch_cooldown[:] = 0.0
    return st, rng


def _play_out(st, cfg, rng, chasers: list[int], max_s: float = 6.0) -> str:
    """Tick until someone controls the ball, a restart is awarded, or the time runs out."""
    t_end = st.t + max_s
    while st.t < t_end:
        if st.ball.owner >= 0:
            return "us" if st.ball.owner < 11 else "them"
        if st.restart is not None:
            return "out"
        targets = st.pos.copy()
        frac = np.zeros(22)
        lead = st.ball.pos + st.ball.vel * 0.4
        for c in chasers:
            targets[c] = lead
            frac[c] = 1.0
        step_players(st, targets, frac, cfg, DT)
        st.t += DT
        st.tick += 1
        step_ball(st, cfg, rng, DT)
    return "none"


def test_pressure(cfg: dict, n: int) -> list[tuple[str, str]]:
    rows = []
    for dist in (None, 4.0, 2.0, 1.0):
        ok = 0
        for k in range(n):
            st, rng = _empty_state(cfg, 1000 + k)
            passer, recv, dfd = 5, 9, 16
            st.caps[passer, CAP_INDEX["passing"]] = 0.7
            st.caps[recv, CAP_INDEX["first_touch"]] = 0.7
            st.pos[passer] = np.array([0.0, 0.0])
            st.pos[recv] = np.array([20.0, 0.0])
            if dist is not None:  # beside the passer, slightly goal-side
                ang = rng.uniform(-np.pi / 2, np.pi / 2)
                st.pos[dfd] = st.pos[passer] + dist * np.array([np.cos(ang), np.sin(ang)])
            st.ball.owner = passer
            st.ball.pos = st.pos[passer].copy()
            st.ball.flight = None
            st.possession = 0
            release(st, BallCommand("pass", st.pos[recv].copy(), "ground", recv), cfg, rng)
            ok += _play_out(st, cfg, rng, [recv, dfd]) == "us"
        label = "no defender" if dist is None else f"defender at {dist:g} m"
        rows.append((f"20 m pass, {label}", f"{ok / n:.0%} completed"))
    return rows


def test_shots(cfg: dict, n: int) -> list[tuple[str, str]]:
    rows = []
    for n_def in (0, 1, 3):
        blocked = goals = 0
        for k in range(n):
            st, rng = _empty_state(cfg, 2000 + k)
            shooter = 9
            st.pos[shooter] = np.array([36.5, 0.0])
            st.pos[11] = np.array([51.0, 0.0])  # their keeper on the line
            for j in range(n_def):
                st.pos[12 + j] = np.array([42.0 + 2.0 * j, rng.uniform(-1.5, 1.5)])
            st.ball.owner = shooter
            st.ball.pos = st.pos[shooter].copy()
            st.possession = 0
            n_ev = len(st.events.events)
            release(st, BallCommand("shoot", np.array([52.5, 0.0]), "shot", -1), cfg, rng)
            _play_out(st, cfg, rng, [], max_s=3.0)
            types = [e.type for e in st.events.events[n_ev:]]
            blocked += "shot_blocked" in types
            goals += "goal" in types
        rows.append((f"16 m central shot, {n_def} defender(s) in the line",
                     f"{blocked / n:.0%} blocked, {goals / n:.0%} goals"))
    return rows


def test_fatigue(cfg: dict, n: int) -> list[tuple[str, str]]:
    rows = []
    for label, frac in (("sprinting", 1.0), ("jogging (half speed)", 0.5)):
        st, rng = _empty_state(cfg, 3000)
        p = 5
        st.caps[p, CAP_INDEX["stamina"]] = 0.5
        st.caps_base = st.caps.copy()
        st.fatigue[:] = 0.0
        v0 = float(max_speed(st, cfg)[p])
        st.pos[p] = np.array([0.0, -25.0])
        out, up = [], 1.0
        for minute in range(1, 16):
            for _ in range(600):
                if abs(st.pos[p][1]) > 25.0 and np.sign(st.pos[p][1]) == up:
                    up = -up  # shuttle runs across the pitch
                tgt = st.pos.copy()
                tgt[p] = st.pos[p] + np.array([0.0, 50.0 * up])
                f = np.zeros(22)
                f[p] = frac
                step_players(st, tgt, f, cfg, DT)
                st.t += DT
            if minute in (1, 5, 15):
                out.append(f"{float(max_speed(st, cfg)[p]) / v0:.0%} at {minute} min (fatigue {st.fatigue[p]:.2f})")
        rows.append((f"top speed while {label}", ", ".join(out)))
    return rows


TESTS = {"pressure": test_pressure, "shots": test_shots, "fatigue": test_fatigue}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--test", choices=list(TESTS), nargs="*", default=list(TESTS))
    ap.add_argument("--n", type=int, default=400, help="repetitions per case")
    a = ap.parse_args()
    cfg = load_config("sim")
    print("| Case | Result |\n|---|---|")
    for t in a.test:
        for case, res in TESTS[t](cfg, a.n):
            print(f"| {case} | {res} |", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
