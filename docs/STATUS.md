# Status

Task and objective tracker. Statuses: `not started` · `in progress` · `blocked` · `done`.

Milestones deliberately follow the design doc's build order (§6): the space layer and a
"is this good for us right now" scoring function come before the ranking graph, and both come
before the generative model. See D-008.

**Last updated:** 2026-09-11 (M2)

| Milestone | State | Summary |
|---|---|---|
| **M0** — Space & feasibility foundation | `done` | Domain model, pitch-control / lane / xT layer, kinematic feasibility, debug renderer |
| **M0.5** — Player roles & matching | `done` | Attributes, positional slots vs. play roles, roster loading, the two role hard-checks |
| **M1** — Play ranking system (module 2) | `not started` | Weighted graph, hard-constraint pre-filter, assignment solve, hand-authored plays |
| **M2** — Dashboard & opponent model (module 1) | partial | Spine, measurements, marking + pressing inference, our own book. Opponent *attributes* still uninferred |
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
| Tests on analytically-known cases | `done` | — | 151 tests (273 across the repo after M0.5) |

### M0 follow-ups (not blocking, worth doing before M1 grows)

| Task | Status | Notes |
|---|---|---|
| Verify geometry mirrors correctly across attacking direction | `done` | Q-011 closed — `TestDirectionAgnostic` in `tests/test_pitch_control.py` |
| Measure per-epoch cost of a full-pitch control field | `not started` | Feeds Q-012 and D-009's backtrack trigger |
| Replace remaining hard constraints' stubs as `Play` lands | `not started` | `single_ball`, `player_count`, `possession_state`, `time_remaining`, `set_piece_context` (§5) |

---

## M0.5 — Player roles & matching `done`

Built ahead of M1 because the assignment problem needs something to assign. Deliberately
stops short of the cost matrix: coverage is answerable now, ranking is not (D-020).

| Task | Status | Blocked by | Notes |
|---|---|---|---|
| Attribute model (13 attributes, 0–100) | `done` | — | `soccersim/domain/attributes.py`; D-019. A test enforces that every attribute is read by some role |
| SI ↔ 0–1 projection for physical capability | `done` | — | `PHYSICAL_RANGES`; handles `reaction_time`'s inverted sense. Ranges uncalibrated (Q-020) |
| `PositionalRole` — formation slots | `done` | — | In `entities.py` to avoid an import cycle; D-018 |
| `PlayRole` — the §4 `RoleRequirement` | `done` | — | Weights + sparse minimums + advisory affinities + hard `required_slots` |
| Role catalogue | `done` | — | 12 roles, each justified by a named §3 play. Completeness unverified until plays exist (Q-022) |
| Fit scoring with explanations | `done` | — | `RoleFit` carries contributions, unmet minimums, limiting factor. Raw `[0,1]`, not a cost (D-022) |
| Fatigue degrades physical fit inputs | `done` | — | Extends D-006 into matching; technical attributes unaffected (Q-021) |
| `practised_roles` for `role_familiarity` | `done` | — | Binary set; graded familiarity is Q-024 |
| Roster schema + strict loader | `done` | — | `domain/roster.py`; rejects unknown keys/slots/roles, duplicate ids, off-scale values, and away rosters |
| Template roster file | `done` | — | `data/rosters/home.json` — **placeholder, meant to be replaced** |
| Roster/snapshot split | `done` | — | Roster = constant identity; snapshot = position/velocity/stamina. Fixtures merge the two |
| `eligibility` hard check | `done` | — | `constraints/roles.py` |
| `min_role_coverage` hard check | `done` | — | Per-attribute minimums, so no dependency on Q-001; reports the closest near-miss and its margin |
| `player_count` (role-layer form) | `done` | — | More distinct roles than available players |
| `validate_roster.py` CLI | `done` | — | Validates, prints coverage, flags depth-1 roles and unpractised best-fits; non-zero exit for CI |

### M0.5 follow-ups

| Task | Status | Notes |
|---|---|---|
| Replace the placeholder roster with the real squad | `not started` | The one task that needs you, not code |
| Calibrate `PHYSICAL_RANGES` against tracking data | `blocked` | Q-020; needs SoccerNet ingest (M3) |
| Revisit the catalogue once plays exist | `not started` | Q-022 — the first three authored plays are the real test |
| Flank-relative footedness for inverted roles | `blocked` | Q-023; needs play context (Q-009) |

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
| Convert `role_fit` scores into capability-match edge weights | `not started` | **Q-001** | The deliberate M0.5 cut line (D-022) — one conversion at the boundary, not a rewrite |
| Hard-constraint pre-filter over candidate plays | `not started` | — | Reuses M0 checks plus M0.5's `check_role_requirements`; D-005 |
| Soft constraints as named `(state, play, assignment)` functions | `not started` | Q-001 | §5; 13 named constraints |
| Hungarian assignment solve | `not started` | — | `scipy.optimize.linear_sum_assignment`; trivial at ~11 roles. Candidates now come from `role_coverage` |
| `total_play_score` combining path weight + assignment cost | `not started` | Q-002 | |
| Hand-author 3 plays (Overlap, Switch-and-cross, Direct vertical counter) | `not started` | Q-009 | §3 |
| End-to-end selection on a fixture snapshot | `not started` | — | The M1 exit criterion |
| Coefficient tuning harness | `blocked` | Q-006, Q-014 | Do **not** tune against the placeholder xT surface |

---

## M2 — Dashboard & opponent model (module 1) `partial`

Built: the stateful spine, every single-frame measurement, two inferences with confidence,
and our own play book. Not built: opponent attribute inference and the cross-possession
book on the opponent — which remain the blocking gap for opponent role matching.

| Task | Status | Blocked by | Notes |
|---|---|---|---|
| **Stateful observer spine** | `done` | — | `dashboard/observer.py`; time-bounded buffer, events derived from carrier deltas, possession segmentation (D-024) |
| Confidence machinery | `done` | — | `dashboard/estimate.py`; decayed observation counts + maturity gate, so an immature estimate cannot be acted on by accident (D-023) |
| Formation-shape metrics (centroid, width, depth, compactness) | `done` | — | Already on `TeamState`; `team_shape` composes rather than forks them |
| Defensive-line height, tilt, width, gaps | `done` | — | `defensive_line`; `largest_gap_between` is what §3's CB–fullback-gap waypoint needs |
| Block height and high/mid/low classification | `done` | — | Thresholds conventional, not fitted (Q-025) |
| **Pressure on the ball carrier** | `done` | — | The §2 item M0 was missing. Only opponents who can actually arrive contribute — an earlier version let defenders drifting back past the ball register as a press |
| Zone occupancy and situation key | `done` | — | Situation granularity unverified until plays exist (Q-026) |
| Marking-scheme inference (man vs. zonal) | `done` | — | Four signals (D-027); recovers both schemes plus per-defender assignments and zone estimates from scripted ground truth |
| Pressing-trigger detection and press intensity | `done` | — | Conditional rates with deferred labelling (D-025), so a common pass type is not mistaken for a trigger |
| Historical "book" — **our own** plays | `done` | — | `dashboard/book.py`; §5's `predictability_penalty` and `historical_success_rate`. Needs no inference |
| Scripted scenarios with ground truth | `done` | — | `soccersim/scenarios.py`; two positive cases, two negative controls (D-026) |
| `dashboard_report.py` CLI | `done` | — | Scores every estimator against planted truth; non-zero exit on failure |
| Per-defender tendency estimates | `not started` | Q-008 | Recovery speed, 1v1 rate, jockey-side preference |
| **Infer opponent attributes** | `not started` | **Q-008** | Away players still carry `attributes=None` (D-021). Now the single blocking gap for opponent role matching — the spine and confidence machinery it needs are in place |
| Historical book on the **opponent** | `not started` | Q-008, Q-028 | Feeds §5's `mismatch_bonus`; needs cross-match persistence |
| Set-piece marking assignments | `not started` | Q-010 | |
| Fatigue / stamina model over match time | `not started` | — | Still a static field; already degrades arrival times and role fit |
| Game-state transitions (clock, phase) | `not started` | — | The observer reads phase changes but nothing drives them |

### M2 follow-ups

| Task | Status | Notes |
|---|---|---|
| Replace nearest-neighbour marking with assignment stability | `not started` | Q-027; fixes zonal false positives and handles switching marks. Reuses M1's Hungarian solve |
| Sweep the dashboard's ~12 thresholds on held-out scenarios | `not started` | Q-025 — current values were set against the scenarios that test them |
| Seed the opponent model before kickoff | `not started` | Q-028; a persisted per-opponent book is what §2's "running book" implies |
| Run our own team through the estimators as a live check | `not started` | Q-029; we know our own scheme, so we are the ideal labelled case |

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
| pytest suite + analytic test cases | `done` | — | 403 tests; run with `-W error::RuntimeWarning` to keep NaN/overflow surprises out |
| Static snapshot renderer | `done` | — | D-011 |
| Tick-based sim loop | `not started` | Q-012 | Needed once M1 selection runs, to see abort-and-reselect (D-002). `scenarios.py`'s stepper is test scaffolding, **not** this |
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
