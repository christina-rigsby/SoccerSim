# Status

Task and objective tracker. Statuses: `not started` · `in progress` · `blocked` · `done`.

Milestones deliberately follow the design doc's build order (§6): the space layer and a
"is this good for us right now" scoring function come before the ranking graph, and both come
before the generative model. See D-008.

**Last updated:** 2026-10-01 (self-play spec M0–M9)

## Self-play spec milestones (`docs/soccer_selfplay_spec.md`)

The spec is implemented as a second stack beside the M1a play engine (D-043). Its
milestone numbers are its own and are prefixed `S-` here to avoid clashing with the
design-doc milestones below.

| Milestone | State | Acceptance evidence |
|---|---|---|
| **S-M0** schema, configs, loader, validator | `done` | 12 starter plays validate; 11 invalid fixtures fail with clear errors (`tests/test_schema.py`); CI runs pytest + ruff |
| **S-M1** simulator core | `done` | Per-model unit tests, deterministic replay from seed, ≥ 20× real time (~130× measured, 4 workers ~150×) (`tests/test_sim_core.py`) |
| **S-M2** controllers + shape | `done` | One scenario test per action type (`tests/test_controllers.py`) |
| **S-M3** Module 1 geometry + predicates | `done` | Every predicate unit-tested; symmetric pitch control = 0.5 (`tests/test_predicates.py`) |
| **S-M4** play executor | `done` | Every starter play runs in a pinned scenario where its own triggers hold; mirror test (`tests/test_executor.py`) |
| **S-M5** Module 2 + replay viewer | `done` | Full scripted match end to end; HTML replay with plays, roles, targets, decision inspector (`tests/test_ranking.py`) |
| **S-M6** self-play runner, logging, league styles, sim xT | `done` | 203,307 decisions from 14,000 games; summary report; xT refit from 230k moves (`tests/test_selfplay_pipeline.py`) |
| **S-M7** encoder, critic, response model | `done` | Critic beats the per-play mean on held-out games; ranking A/B with vs without critic in `data/models/critic_metrics.json` |
| **S-M8** tokenizer, grammar generator, BC + mutation | `done` | 100 % validity by construction (target > 99 %); matched-scenario EPV comparison in `generator_metrics.json` |
| **S-M9** PPO league, QD archive, promotion | `done` (quick profile) | League history, Elo, payoff, archive, final evaluation vs every scripted style incl. held-out `possession`; promoted plays in `plays/generated_and_promoted/run_<N>/` (one folder per league run) |
| **S-M10** GRF adapter, SoccerNet calibration | `not started` | Optional per spec; Q-036 |

Runs so far use the `quick` training profile. The `spec` profile (model sizes and run
lengths from the spec) is configured but has not been run.

### Results of the 2026-10-01 quick run

| Check | Result | Target met? |
|---|---|---|
| Phase A data | 203,307 decisions from 14,000 library self-play games (~150× real time on 4 cores) | yes |
| Critic vs per-play mean (held-out MSE) | 0.000333 vs 0.000391 (−15 %); success accuracy 87 % | yes |
| Ranking with critic vs without (60 matched games) | 0.00168 vs 0.00177 mean play reward | **no** — flat; the critic rarely changes the choice because few library plays are feasible at once |
| Response model, opponent's next play | 69 % accuracy vs 28 % majority guess | — |
| Generator validity | 100 % (grammar-constrained) | yes |
| Generated vs library EPV, matched scenarios | −0.0030 vs −0.0041 mean play reward | yes (≥ 80 %) |
| League (6 updates, 96 games) | main Elo 1028; archive 44 plays / 23 elite niches; 6 plays promoted for review | archive grows: yes |
| Main agent vs scripted styles | better than the library vs `high_press`, level vs held-out `possession`, worse vs `mid_block` and `low_block_counter` | **no** — needs the `spec`-length league |
| Held-out physics check | EPV dropped 41 % under held-out physics | **flagged** (possible sim overfitting) |
| Shots | library self-play: 37 shots in ~6,650 sim-minutes; agent: 0 in 16 highlight games | see Q-035 |


### Results of run 3, opponent pool v2 (2026-10-07)

Pool v2 (D-045): seven scripted styles, `possession` and `wing_play` held out of all training
data; library of 29 plays (18 hand-written incl. six build-up plays, 11 promoted from runs 1-2
adopted in their niche, D-046). Run 3 on pool v1 was skipped. Compared with the pool v1 run:

| Check | Pool v1 (runs 1-2) | Pool v2 (run 3) |
|---|---|---|
| Decisions where only recycling fits | 82 % | 20 % |
| Possessions that never get past recycling | 54 % | 7 % |
| Own third: only recycling fits | 95 % | 14 % |
| Decisions per possession | 2.9 | 1.7 |
| Library gap rate (only circulation + weak fit) | 97 % | 94 % (mostly "weak fit": a play fits but scores < 0.03) |
| Critic vs per-play mean (held-out MSE) | −15 % (40k rows) | −8 % (162k rows); outcomes 34 % more variable; plateaued after epoch 5 |
| Critic vs overall mean | −32 % | −23 % |
| Ranking with critic vs without (60 matched games) | flat (0.0017 vs 0.0018) | **better: 0.0050 vs 0.0010** mean play reward |
| Generator validity / matched vs library | 100 % / −0.0030 vs −0.0041 | 100 % / −0.0028 vs −0.0053 |
| Main agent vs library, per style | better vs 1 of 4 | better vs `direct`, held-out `possession`; level vs `mid_block`; worse vs `chaotic`, held-out `wing_play`, slightly vs `high_press`, `low_block_counter` |
| Regression gate | run 2 passed | passed vs all 7 styles (run 4 may continue from run 3) |
| Held-out physics check | −41 % (flagged) | −35 % (flagged) |
| Promoted | 6 (run 2) | 6 (`plays/generated_and_promoted/run_3/`) |
| Generated plays that succeeded | not recorded | 259 times, 141 plays (`reports/run_3/generated_successes/`) |
| Validation round-robin (8 games per pair, every pair incl. held-out styles) | — | average score vs the 7 styles: library 0.55, library + critic 0.47, main agent 0.46; main beats library + critic 0.69, ties library 0.50 (small samples: ±0.17 per cell) |
| Reward distributions (all league plays) | — | median ≈ 0 for generated and library plays; generated: 7 % of plays > +0.005, 17 % < −0.005; library: 12 % / 17 %. No right shift over 6 updates |

## Design-doc milestones

| Milestone | State | Summary |
|---|---|---|
| **M0** — Space & feasibility foundation | `done` | Domain model, pitch-control / lane / xT layer, kinematic feasibility, debug renderer |
| **M0.5** — Player roles & matching | `done` | Attributes, positional slots vs. play roles, roster loading, the two role hard-checks |
| **M1a** — Play building (module 2, part 1) | `done` | Anchors, triggers, the play DAG, 7 authored plays, instantiation, executor |
| **M1b** — Ranking graph & weight algebra | `done` (spec stack) | Built as S-M5: EPV weight algebra (D-042), Hungarian assignment, scoring |
| **M2** — Dashboard & opponent model (module 1) | partial | Spine, measurements, marking + pressing inference, our own book. Opponent *attributes* still uninferred |
| **M3** — AI/ML play generator (module 3) | `done` (spec stack) | Built as S-M7–S-M9 after the hand-authored library ran end to end, honouring D-008 |
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

## M1b — Ranking graph & weight algebra `not started`

**Being built elsewhere.** Listed so the interfaces are clear and nothing here duplicates
it.

| Task | Status | Blocked by | Notes |
|---|---|---|---|
| **Pick the weight algebra** | `not started` | **Q-001** | Gates everything else here |
| Graph schema (Objective / Strategy / Play / RoleRequirement / Constraint / Player) | `not started` | Q-001 | §4 |
| Edge-weight functions, recomputed per epoch | `not started` | Q-001 | §4 "weights are functions, not constants" |
| Convert `role_fit` scores into capability-match edge weights | `not started` | Q-001 | D-022's cut line |
| **Add a positional term to the assignment cost** | `not started` | Q-032 | Found by running M1a's pipeline: capability fit alone assigns unreachable players. Ingredients exist — `time_to_point` and `Play.time_budget` |
| Hungarian assignment solve | `not started` | Q-001 | Replaces M1a's greedy stand-in (D-030) |
| Soft constraints as named `(state, play, assignment)` functions | `not started` | Q-001 | §5; 13 constraints. `chain_depth`, `single_ball` and the dashboard's inputs are all computable now |
| `total_play_score` combining path weight and assignment cost | `not started` | Q-002 | |
| Hard-constraint pre-filter over candidate plays | `not started` | — | M1a's `InstantiatedPlay.violations()` already does this per play; the pre-filter orders it |
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
| pytest suite + analytic test cases | `done` | — | 529 tests; run with `-W error::RuntimeWarning` to keep NaN/overflow surprises out |
| Static snapshot renderer | `done` | — | D-011 |
| Tick-based sim loop | `not started` | Q-012 | Needed once M1b selection runs, to see abort-and-reselect across plays. `scenarios.py`'s stepper and `plays/rehearsal.py` are test scaffolding, **not** this |
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
