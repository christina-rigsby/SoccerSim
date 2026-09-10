# Status

Task and objective tracker. Statuses: `not started` · `in progress` · `blocked` · `done`.

Milestones deliberately follow the design doc's build order (§6): the space layer and a
"is this good for us right now" scoring function come before the ranking graph, and both come
before the generative model. See D-008.

**Last updated:** 2026-09-10

| Milestone | State | Summary |
|---|---|---|
| **M0** — Space & feasibility foundation | `done` | Domain model, pitch-control / lane / xT layer, kinematic feasibility, debug renderer |
| **M1** — Play ranking system (module 2) | `not started` | Weighted graph, hard-constraint pre-filter, assignment solve, hand-authored plays |
| **M2** — Dashboard & opponent model (module 1) | `not started` | Opponent inference, the running "book", game-state tracking |
| **M3** — AI/ML play generator (module 3) | `blocked` | Blocked on M0+M1 validation with hand-authored plays, per D-008 |
| **X** — Cross-cutting | partial | Sim loop, tuning harness, test infrastructure |

---

## M0 — Space & feasibility foundation `done`

| Task | Status | Blocked by | Notes |
|---|---|---|---|
| Project scaffold (`pyproject.toml`, package layout, pytest) | `done` | — | |
| Three tracking docs seeded from the design doc | `done` | — | This file, `OPEN_QUESTIONS.md`, `DECISIONS.md` |
| `Pitch` geometry + zone/third/channel helpers | `done` | — | Coordinate convention per D-012 |
| `PlayerState` / `BallState` / `TeamState` / `GameState` | `done` | — | Fatigue as capability degradation (D-006) |
| `Waypoint` primitive | `done` | — | D-014; `deadline` is a placeholder pending Q-009 |
| Canonical fixtures (kickoff, wing overload, counter) | `done` | — | `soccersim/domain/fixtures.py`; shared by tests and demo |
| `kinematics.time_to_point` (trapezoidal + turn cost) | `done` | — | The load-bearing function — used by *both* pitch control and the `max_speed` constraint. Turn model provisional (D-017 / Q-015) |
| `PitchGrid` shared grid abstraction | `done` | — | One grid for control, threat, and lane sampling |
| Pitch-control field | `done` | — | D-013; λ uncalibrated (Q-005) |
| Passing-lane assessment + cover shadow | `done` | — | Constant ball speed (D-016 / Q-007) |
| xT surface behind a `ThreatSurface` protocol | `done` | — | Uncalibrated analytic prior (D-015 / Q-006) |
| Hard checks: reachability, bounds, offside, separation | `done` | — | The subset the foundation can honestly support |
| matplotlib debug renderer | `done` | — | D-011; static snapshots only |
| Demo script writing `out/snapshot.png` | `done` | — | `scripts/demo_snapshot.py` |
| Tests on analytically-known cases | `done` | — | 151 tests |

### M0 follow-ups (not blocking, worth doing before M1 grows)

| Task | Status | Notes |
|---|---|---|
| Verify geometry mirrors correctly across attacking direction | `done` | Q-011 closed — `TestDirectionAgnostic` in `tests/test_pitch_control.py` |
| Measure per-epoch cost of a full-pitch control field | `not started` | Feeds Q-012 and D-009's backtrack trigger |
| Replace remaining hard constraints' stubs as `Play` lands | `not started` | `single_ball`, `player_count`, `possession_state`, `time_remaining`, `set_piece_context` (§5) |

---

## M1 — Play ranking system (module 2) `not started`

| Task | Status | Blocked by | Notes |
|---|---|---|---|
| **Pick the weight algebra** | `not started` | **Q-001** | Gates everything else in M1. Do this first |
| Graph schema (Objective / Strategy / Play / RoleRequirement / Constraint / Player nodes) | `not started` | Q-001 | Schema in §4 |
| `Play` type with an action-dependency graph | `not started` | Q-009 | Needed for `chain_depth_penalty` |
| Event-trigger representation for waypoints | `not started` | Q-009 | Replaces `Waypoint.deadline` |
| Objective / Strategy / Play taxonomy from §3 | `not started` | — | 7 objectives, strategies, plays as listed |
| Action vocabulary (on-ball, off-ball, defensive) | `not started` | — | §3; ~25 actions |
| Edge-weight functions (recomputed per epoch, not constants) | `not started` | Q-001 | §4 "weights are functions, not constants" |
| Hard-constraint pre-filter over candidate plays | `not started` | — | Reuses M0 checks; D-005 |
| Soft constraints as named `(state, play, assignment)` functions | `not started` | Q-001 | §5; 13 named constraints |
| Hungarian assignment solve | `not started` | — | `scipy.optimize.linear_sum_assignment`; trivial at ~11 roles |
| `total_play_score` combining path weight + assignment cost | `not started` | Q-002 | |
| Hand-author 3 plays (Overlap, Switch-and-cross, Direct vertical counter) | `not started` | Q-009 | §3 |
| End-to-end selection on a fixture snapshot | `not started` | — | The M1 exit criterion |
| Coefficient tuning harness | `blocked` | Q-006, Q-014 | Do **not** tune against the placeholder xT surface |

---

## M2 — Dashboard & opponent model (module 1) `not started`

| Task | Status | Blocked by | Notes |
|---|---|---|---|
| Formation-shape metrics (centroid, width, depth, compactness) | `not started` | — | §2; straightforward from positions |
| Defensive-line height and compactness tracking | `not started` | — | |
| Marking-scheme inference (man vs. zonal) | `not started` | Q-008 | Inference problem, not a measurement |
| Pressing-trigger detection and press intensity | `not started` | Q-008 | |
| Per-defender tendency estimates | `not started` | Q-008 | Recovery speed, 1v1 rate, jockey-side preference |
| Historical "book" — per-possession updates | `not started` | Q-008 | Feeds `mismatch_bonus` and `predictability_penalty` |
| Set-piece marking assignments | `not started` | Q-010 | |
| Fatigue / stamina model over match time | `not started` | — | Currently a static field on `PlayerState` |
| Game-state tracking (score, clock, phase, ball state) | partial | — | Types exist in `domain/state.py`; no transitions yet |

---

## M3 — AI/ML play generator (module 3) `blocked`

Blocked on M0+M1 validation with hand-authored plays (D-008). Listed for completeness.

| Task | Status | Blocked by | Notes |
|---|---|---|---|
| SoccerNet-GSR / Tracking ingest | `not started` | M1 | D-007; treat as noisy-continuous |
| Segment tracking into plays via Action Spotting | `not started` | M1 | Possession-start → shot/loss |
| Heuristic objective/strategy labelling + validation | `not started` | Q-019 | Measure label noise before trusting it |
| Per-frame graph state representation (22 players + ball) | `not started` | M1 | GNN or set transformer, permutation-invariant |
| Play generator (transformer decoder vs. diffusion) | `not started` | Q-018 | |
| Feasibility/value critic — `P(success \| state, play)` | `not started` | M1 | Build **before** the generator per D-008 |
| Critic output made commensurable with penalty sum | `not started` | **Q-003** | The integration risk for D-001 |
| RL fine-tuning loop in a simulator | `not started` | Q-016 | GRF vs. custom sim |
| Runtime: sample N, score, hard-filter, execute top | `not started` | M1 | Same replanning cadence as the ranking system |
| Generator activation threshold | `not started` | Q-017 | |

---

## X — Cross-cutting `partial`

| Task | Status | Blocked by | Notes |
|---|---|---|---|
| pytest suite + analytic test cases | `done` | — | 151 tests; run with `-W error::RuntimeWarning` to keep NaN/overflow surprises out |
| Static snapshot renderer | `done` | — | D-011 |
| Tick-based sim loop | `not started` | Q-012 | Needed once M1 selection runs, to see abort-and-reselect (D-002) |
| Animation / match replay output | `not started` | — | After the sim loop |
| Per-epoch performance measurement | `not started` | Q-012 | Decides D-009's backtrack trigger |
| CI (run pytest on push) | `not started` | — | |
| `CLAUDE.md` with repo conventions | `not started` | — | Should point at these three docs |

---

## Update protocol

These docs only stay useful if they are cheap to update:

- Finishing a task → flip its status here.
- Making a design choice → add a `DECISIONS.md` entry **with a backtrack trigger**, and close
  or downgrade the matching `OPEN_QUESTIONS.md` entry.
- Implementing something whose correct form is still unknown → the decision is `provisional`
  and the question stays open. Do not let a working implementation quietly become a settled
  decision; that is the failure mode these three docs exist to prevent.
