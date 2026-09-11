# Open Questions

Unresolved design choices, sourced from `soccer_simulation_design.md` and from
implementation work. Each question carries a status:

| Status | Meaning |
|---|---|
| `open` | No answer yet. Anything depending on it is guessing. |
| `provisional` | Code makes a working choice so progress can continue, but the choice is **not** settled. Cross-referenced to a `DECISIONS.md` entry with a backtrack trigger. |
| `closed` | Settled. Links to the `DECISIONS.md` entry that records it. |

A `provisional` question is the dangerous kind: there is code depending on an answer
nobody has actually committed to. Review these before building anything on top.

**Convention:** never delete a closed question — flip its status and link the decision, so
the reasoning trail survives.

---

## Ranking system (design doc §4)

### Q-001 · Which weight algebra? · `open`
Costs (lower = better), log-probabilities (sum = joint log-likelihood, exponentiate for a
calibrated `P(success)`), or utilities (higher = better, negatives allowed)? The doc says to
"pick one consistent semantics up front" and then does not pick.

*Why it matters:* every edge-weight function, every soft-constraint coefficient, and the
critic's output units all depend on this. Choosing late means rewriting all of them.
*Blocks:* M1 edge-weight work, soft-constraint implementation, critic calibration, and converting `role_fit`'s raw `[0, 1]` score into a Hungarian cost (D-022).
*Leaning:* log-probabilities — the doc notes this is cleanest when edge weights are trained
independently from different data sources, which is exactly the situation (opponent model,
historical success rates, and critic output come from three different places).

### Q-002 · How do path weight and assignment cost combine? · `open`
Two-stage scoring produces two numbers (§4). Sum? Weighted sum? Product? The answer is
constrained by Q-001 — under log-probabilities a sum is the principled choice; under
utilities it is a modelling decision.
*Blocks:* the final `total_play_score` function.

### Q-003 · How is critic output made commensurable with the soft-penalty sum? · `open`
§4 requires that "critic output must be expressed in the same units as the soft-penalty
sum" so generated and hand-authored plays can compete in one ranking pass. A neural net
emitting `P(success)` and a hand-tuned penalty sum are not naturally on one scale.
*Why it matters:* if this is wrong, generated plays either always or never outrank
pre-defined ones, and the single-selection-mechanism design (D-001) collapses.
*Blocks:* M3 integration. *Depends on:* Q-001.

### Q-004 · Scalar collapse or weight vector + Pareto ranking? · `open`
§4 suggests that genuinely incommensurable edge types (injury risk vs. expected xT gain)
might warrant a small weight *vector* per edge with Pareto-ranking over the top candidates.
*Trade-off:* a scalar gives a total order and a trivial argmax; a vector avoids inventing an
exchange rate between "risk of injury" and "goals" but needs a tie-break policy anyway.

---

## Space / geometry layer (design doc §2)

### Q-005 · Which pitch-control model? · `provisional` → D-013
Plain distance Voronoi, time-to-intercept, or the full Spearman pass-probability model?

*Provisional answer:* time-to-intercept sigmoid (D-013). Implemented in
`soccersim/space/pitch_control.py`.
*What would settle it:* rendering control fields for transition snapshots and checking them
against intuition, then against real tracking data once SoccerNet ingest exists.
*Open sub-question:* the sharpness constant `DEFAULT_SHARPNESS` (λ = 1.5, i.e. a 1-second
arrival advantage reads as ~82% control) is a guess, not a fit.

### Q-006 · Where does the xT surface come from? · `provisional` → D-015
Analytic prior, fitted from SoccerNet, or a published xT grid?

*Provisional answer:* an analytic prior (`AnalyticThreatSurface`) that is monotone toward
goal and symmetric about the centre line. It is **not calibrated** — the numbers have the
right shape and meaningless magnitudes.
*Consequence to watch:* tuning any soft-constraint coefficient against this surface is
tuning against a fiction. Do not do it before this closes.

### Q-007 · How is ball travel time modelled for passing lanes? · `provisional` → D-016
`assess_lane` currently assumes constant ball speed. Real passes decelerate (ground) or
follow a ballistic arc (lofted/through), and §3's action vocabulary distinguishes
`ground|lofted|through`.
*Why it matters:* lofted passes travel over defenders entirely, so a 2-D lane occlusion test
is the wrong model for them.

### Q-008 · How is the opponent model actually inferred? · `open`
§2 wants marking scheme (man vs. zonal, with zone boundaries), pressing triggers, press
intensity, trap tendencies, and per-defender tendencies. None of these are observable
directly — they are all inference problems.
*Sub-questions:* online estimator updated per possession, or offline fit between matches?
How many possessions before the "book" is trustworthy enough to weight? What is the prior
before any data exists (league average? scouting input? uninformative?)
*Now has teeth in the code:* away players carry `attributes=None` and `role_fit` refuses to
score them (D-021). Opponent role matching is blocked until this question is answered, which
is the honest state of affairs rather than a gap to paper over with default 50s.

**Partially answered by M2.** Two of the sub-questions are now settled in code:
- *Marking scheme* — inferred from four movement signals (D-027), recovering both
  man-marking and zonal from scripted ground truth, plus per-defender assignments and zone
  estimates.
- *Pressing triggers and intensity* — inferred as conditional rates (D-025).
- *Online or offline?* — online and incremental, over a time-bounded buffer (D-024).
- *What is the prior before any data?* — answered structurally rather than numerically: an
  estimate below its maturity threshold reports nothing actionable, so there is no prior to
  pick (D-023). That defers rather than resolves the question for a Bayesian formulation.

**Still open, and now the blocking remainder:** per-defender tendencies (recovery speed,
1v1 win rate, preferred jockey side), the cross-possession "book" on the opponent, and
above all **opponent attribute inference** — the one that unblocks opponent role matching.

---

## Play representation (design doc §3)

### Q-009 · What is the event-trigger language? · `closed` → D-029
§3 specifies waypoints "timed/triggered relative to events (ball reaches point X, defender
crosses threshold Y) rather than fixed clock time".

*Resolution:* a named registry of parameterised predicates over live state
(`soccersim/plays/triggers.py`), mirroring the anchor registry, so a play stays data all
the way down. 14 trigger kinds including the two §3 names — `ball_within` is "ball reaches
point X", `opponent_within`/`role_beyond` are "defender crosses threshold Y" — plus
combinators. The same vocabulary serves activation, completion and **abort**, which is what
makes D-002's "willing to abort mid-play" a mechanism rather than an aspiration.

`elapsed` survives as a deliberate fallback: some steps are genuinely timed, and every step
needs a timeout or a play whose trigger never fires hangs (D-031).

*Knock-on effects:* `Waypoint.deadline` is no longer hand-authored but **derived** from the
step graph (D-029), closing D-014's placeholder. And offside moved to the moment of the pass
(D-033), closing the approximation M0's `check_offside` flagged as pending this question.

### Q-010 · Are set pieces a branch of the same graph, or a separate taxonomy? · `open`
"Convert set piece" and "Defend set piece" appear as objectives (§3), and
`set_piece_context` is a hard constraint (§5). But set-piece plays have almost no structural
overlap with open-play plays — fixed starting positions, no pitch control gradient to exploit
at the moment of the restart, marking assignments rather than lanes.

### Q-011 · Do plays generalise across attacking direction automatically? · `closed`
Waypoints are defined against the pitch-control layer (D-003), which should make this free.

*Resolution:* verified for the space layer. `fixtures.mirrored()` flips a whole game state in
`x`, and `TestDirectionAgnostic` asserts that the control field mirrors exactly and that
controlled area is preserved. `time_to_point` has its own mirror test.
*Caveat:* this closes the question for **geometry**, not for plays — there are no plays yet.
Re-open as a checklist item when M1 lands hand-authored plays, since a play could still hard-
code a sign somewhere the geometry does not.

---

## Play building (added M1a)

### Q-030 · Plays are flank-specific, and the library only has right-sided variants · `open`
`overlap_right`, `underlap_right` and `trap_press` all hardcode `flank: "right"`. The same
play on the left needs a second file, and the library currently lacks one — so
`trap_press` correctly refused to fit a fixture where the ball was left of centre, for the
wrong reason: there simply is no left-sided trap.

*Why it matters:* it doubles the library for no tactical content, and a ranking layer
choosing between `overlap_right` and `overlap_left` is choosing between two spellings of
one play rather than two ideas.
*The fix, and it is a design change:* give `Play` **parameters** and let a step's anchors
reference them (`flank: "$side"`), so one play file covers both sides and the ranking layer
picks the side as part of selection. The anchors already take flank as a parameter; it is
the play file that hardcodes it.
*Cheaper interim:* generate mirrored variants at load time.

### Q-031 · Are the step timeouts right? · `provisional` → D-029
Every step carries a timeout, and they were authored by judgement. Several plays are
infeasible against the fixtures purely because a run needs 5.7 s and the step allows 5.0 s.

*Why it matters:* timeouts do double duty — they bound the step *and* they set the waypoint
deadline the kinematic check uses, so a tight timeout reads as physical infeasibility. Too
generous and a stalled play lingers instead of reselecting; too tight and good plays are
never selected.
*What would settle it:* derive the deadline from the anchor distance and the assigned
player's capability rather than authoring it, keeping the timeout for the *abort* horizon
only. That separates two things currently conflated in one number.

### Q-032 · The assignment cost needs a positional term, not just capability · `open` (hand-off)
Running the pipeline with the greedy stand-in (D-030) surfaced this: it assigned a
full-back 30 m from the play's first waypoint, and a left winger to a right-flank play,
because §4's capability-match edge describes *capability* and says nothing about **where
the player currently is**.

*For whoever builds the assignment solve:* the cost matrix wants a reachability term
alongside capability fit. The ingredients exist — `kinematics.time_to_point` already gives
arrival time, and `Play.time_budget(step)` gives the deadline, so the slack for a
candidate's first waypoint is computable today. Whether that belongs as a second edge
weight, a hard pre-filter, or a Pareto dimension (Q-004) is a weight-algebra question.

### Q-033 · Should sustained actions have a duration distinct from their timeout? · `open`
A sustained action (`mark_man`, `cover_shadow`, `hold_position`) completes once held for
its `timeout`, because there is no arrival moment. That overloads one field: "hold this for
3 s" and "give up after 3 s" are different statements that currently cannot differ.

*Practical consequence:* a press whose cover-shadow should be held for the whole play has
to declare a long timeout, which also makes it slow to abort.

---

## Dashboard and opponent model (added M2)

### Q-025 · Are any of the dashboard's thresholds right? · `provisional` → D-023, D-027
The estimators are built on roughly a dozen constants, none fitted:

| Constant | Value | Governs |
|---|---|---|
| `DEFAULT_HALF_LIFE` | 180 s | how fast opponent evidence is forgotten |
| `USAGE_HALF_LIFE` / `OUTCOME_HALF_LIFE` | 300 s / 3600 s | play-usage vs. success-rate decay |
| `PRESS_ONSET` | 0.75 | intensity at which a press is "underway" |
| `TRIGGER_LOOKAHEAD` | 2.5 s | how long after a pass a press counts as triggered by it |
| `MIN_TRIGGER_RATE` | 0.55 | rate above which a trigger is reported |
| `STABILITY` / `ALIGNMENT` / `MARKING_RADIUS` / `DISTANCE_VARIATION` | 0.60 / 0.45 / 8 m / 3.5 m | the four marking signals |
| `LOW_BLOCK_CEILING` / `HIGH_BLOCK_FLOOR` | 0.34 / 0.72 | block classification |
| maturity thresholds | 4–30 obs | when an estimate becomes actionable |

*Why it matters:* these set both sensitivity and how long the model takes to become
useful. The scenarios show the current values recover planted behaviour, but a scenario the
thresholds were tuned against is weak evidence — that is close to fitting the test.
*What would settle it:* a sweep over each constant measuring recovery accuracy and
time-to-maturity on *held-out* scenarios, then real tracking data (D-007).

### Q-026 · Is `situation_key` the right definition of "similar"? · `provisional`
§5's `predictability_penalty` is proportional to recent usage "against similar opponent
situations". The current key is `(ball third, opponent block, match phase)` — 3 × 3 × 4 = 36
buckets at most.

*The tension:* too coarse and genuinely different situations share a bucket, so a play looks
repetitive when it was a response to different problems. Too fine and every situation is
unique, so nothing ever looks repetitive and the penalty never fires.
*Not yet testable:* no plays exist (M1), so nothing has exercised the bucketing.

### Q-027 · Zonal defenders who sit close to one attacker read as markers · `open`
In the zonal scenario, 2 of 11 defenders are reported as man-marking. They are the wide
midfielders, who happen to sit ~2 m from the opposing wingers and slide with the ball — by
the four signals in D-027 that is indistinguishable from marking.

*Quantified rather than tuned away.* Tightening thresholds until this specific scenario
came out clean would be fitting to the scenario. The team-level verdict is correct
(13% man-share against a 60% majority bar), and `marker_of` requires maturity, so the
practical impact today is small.
*The real fix, when it matters:* infer marking as *assignment stability* — solve a
bipartite matching between defenders and attackers each frame and measure how stable the
matching is — rather than as per-defender nearest-neighbour tracking. That also handles
defenders switching marks, which the current approach cannot express at all. It needs the
Hungarian machinery M1 brings anyway.

### Q-028 · How should the opponent model be seeded before kickoff? · `open`
Every estimate starts immature, so for the opening minutes the ranking layer has no
opponent model at all.

*Why it matters:* §5's `mismatch_bonus` and `score_time_alignment` are inert early, which
is safe but wasteful — a scouting report or last season's data would be informative from
the first whistle.
*Options:* a persisted per-opponent book carried between matches (which is what §2's
"running book on the opponent" implies); a league-average prior; manual scouting input.
*Interacts with:* Q-023's Bayesian alternative, where a prior is the natural mechanism.

### Q-029 · Should our own team be run through the estimators as a check? · `open`
The dashboard is deliberately asymmetric (D-028): we measure ourselves and infer the
opponent. But we *know* our own marking scheme, which makes us the perfect labelled test
case — running the estimator against ourselves would score it continuously, in real
conditions, with no scripting.

*Cheap to try.* The counter-argument is that it doubles estimator cost per epoch for a
diagnostic, and Q-012's budget is unmeasured.

---

## Player roles and matching (added M0.5)

### Q-020 · Are the physical reference ranges right? · `provisional` → D-019
`PHYSICAL_RANGES` maps SI capability onto 0–1 so role weights can mix it with 0–100
attributes: `max_speed` 5.5–9.2 m/s, `max_accel` 4.5–8.0 m/s², `reaction_time` 0.34–0.14 s.

*Why it matters:* these set how much a physical edge is worth *relative to* a technical
one. Too narrow a range and everyone saturates at 0 or 1, flattening the distinction; too
wide and pace stops mattering. Every role that weights a physical attribute is affected.
*What would settle it:* percentiles from real tracking data (SoccerNet, D-007).

### Q-021 · Should fatigue degrade technical attributes too? · `open`
Fatigue currently degrades only physical inputs to role fit (D-006, extended by D-019):
a tired player is slower, but passes and crosses exactly as well as when fresh.

*Why it matters:* tired players demonstrably make worse decisions and strike the ball
worse. If that is real and unmodelled, late-game role assignments are systematically
over-confident — and late-game is precisely when substitutions and role changes matter.
*Complication:* a blanket degradation would double-count for roles that weight both, and
the right curve is probably not the same for a sprint as for a pass.

### Q-022 · Is the role catalogue complete, and at the right granularity? · `open`
Twelve roles, each justified by a named play in §3. But §3's play list is itself partial,
and no play has actually been authored yet (M1), so nothing has really exercised the
catalogue.

*The specific risk:* roles defined before the plays that consume them tend to be a guess
at what will be needed. The first three hand-authored plays are the real test.
*Open sub-question:* should roles compose (an "overlap runner" being "wide runner" +
"crosser") rather than being flat? Composition would cut duplication in the weight tables.

### Q-023 · How does footedness interact with the flank? · `open`
`inverted_winger` gates on `weak_foot ≥ 55`, which is a proxy. What actually matters is
whether a player's strong foot is the *inside* foot for the flank they are on — a
left-footed player is an inverted winger on the right and an orthodox one on the left.

*Why it matters:* the whole point of the inverted role is cutting inside onto the strong
foot. The current gate would accept a two-footed player on either flank (fine) but cannot
distinguish a left-footed player on the left from one on the right (not fine).
*Blocked on:* a role needs to know the flank it is being assigned on, which is play
context — so this waits for `Play` (Q-009). `PositionalRole.flank` exists ready for it.

### Q-024 · Should `role_familiarity` be graded rather than binary? · `open`
`practised_roles` is a set: you have rehearsed a role or you have not. §5 says
"penalise assigning a player to a role/play they haven't practised, if tracked".

*The question:* is a binary flag enough, or does familiarity need levels (rehearsed /
trained / never), or a count decaying over time like `predictability_penalty` does?
*Note:* this only affects the soft penalty's shape, so it is not urgent — but the data
model has to support whatever is chosen, and widening a set to a mapping later touches
every roster file.

---

## Replanning (design doc §1)

### Q-012 · 0.5s or 1s replanning cadence, and what is the full trigger list? · `open`
The doc gives "~0.5–1s or on trigger events (e.g., a defender closing a passing lane faster
than expected)" and one example trigger.
*Why it matters:* the cadence sets the compute budget for the whole per-epoch pipeline, which
in turn decides whether Python is viable (see D-009's backtrack trigger).
*Needs:* an enumerated trigger list, and a measurement of actual per-epoch cost.

### Q-013 · Does an aborted mid-play count as a failure? · `open`
§1 says be willing to abort mid-play and reselect. §5 has `historical_success_rate` as the
feedback loop.
*The problem:* if aborting counts as failure, the system learns to avoid plays that are
correctly abandoned, which punishes exactly the behaviour the receding-horizon design wants.
If it does not count at all, a play that reliably needs abandoning looks free.
*Possible answer:* credit the abort to the *replanning decision* rather than the play, or
score partial progress (did it advance the objective before aborting?).

---

## Constraints (design doc §5)

### Q-014 · How are soft-constraint coefficients tuned, and against what metric? · `open`
§5 offers "RL fine-tuning loop or grid search against simulated match outcomes".
*Chicken-and-egg:* tuning against simulated outcomes needs a trustworthy simulator, which is
Q-016. Tuning against real match outcomes needs far more data than one team generates.
*Also unresolved:* what the outcome metric is. Goals are too sparse to tune against directly;
xT gain per possession is denser but only as good as Q-006.

### Q-015 · What is the turn-cost model in `time_to_point`? · `provisional` → D-017
The current model charges `|v_perpendicular| / max_accel` to redirect. This is an
approximation, not physics: real players turn along curved paths and lose speed to the turn
itself.
*Why it matters:* `time_to_point` is the single most load-bearing function in the codebase —
both pitch control and the `max_speed` hard constraint call it. Systematic error here biases
everything downstream in the same direction.
*What would settle it:* fit against SoccerNet-Tracking acceleration/turn profiles.

---

## Module 3 — ML generator (design doc §6)

### Q-016 · Which simulator for the RL fine-tuning loop? · `open`
Google Research Football (standard, open, but its own physics and action space) vs. a
lightweight custom simulator on the pitch-control layer (matches our representation exactly,
but is a large build and risks learning our own modelling errors).

### Q-017 · What threshold triggers the generator? · `open`
Module 3 activates "when no pre-defined play scores above threshold" (§6). The threshold's
meaning depends entirely on Q-001, and its value trades off novelty against reliability.
*Also:* is it a fixed constant, or a function of game state (more willing to improvise when
losing late)?

### Q-018 · Transformer decoder or diffusion for the generator? · `open`
§6 notes diffusion handles multimodality well — there are usually several plausible good
plays, not one deterministic answer — and matches recent multi-agent sports-trajectory work.
*Deferred:* blocked behind M0/M1 validation per D-008, so no need to answer soon.

### Q-019b · What is SoccerNet actually good for, for plays? · `open` (deferred by choice)
Considered when play building started, and deliberately deferred.

*Recommendation on record:* the highest-value use is **calibrating anchor parameters**, not
mining play templates. How far behind the line runners actually go, typical CB–fullback gap
widths, realistic cross origins and delivery depths — every free number in
`soccersim/plays/anchors.py` is a distribution that could be fitted. That needs only the
ball and the defensive line, which broadcast tracking captures best.

*Why not mine whole plays:* the off-ball structure that *defines* a play is exactly what
broadcast video loses (D-007's known limitation — off-screen players). The overlap runner in
a wing overload is often not in frame. Mining would likely yield on-ball fragments rather
than plays.

*Middle option:* use Action Spotting to segment possessions and measure how often real
sequences match a hand-authored template — a reality check on the library, though match
rates are confounded by the same missing players.

### Q-019 · How reliable is heuristic objective/strategy labelling? · `open`
§6 step 2 proposes rule-based labelling of SoccerNet segments ("ended in a shot from a cross
→ wing overload"). Unvalidated. If label noise is high, supervised pretraining learns the
heuristic's mistakes rather than the game.
*Cheap check:* hand-label a few hundred segments and measure agreement.
