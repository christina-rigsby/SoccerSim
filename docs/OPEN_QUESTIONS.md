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
*Blocks:* M1 edge-weight work, soft-constraint implementation, critic calibration.
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

---

## Play representation (design doc §3)

### Q-009 · What is the event-trigger language? · `open`
§3 specifies waypoints "timed/triggered relative to events (ball reaches point X, defender
crosses threshold Y) rather than fixed clock time" — but no concrete representation.

*Why it matters:* this is the core play data structure. `Waypoint` currently carries an
absolute `deadline` in seconds (D-014), which is a deliberate simplification that must be
replaced, not extended.
*Options sketched:* a small predicate DSL over game state; a dependency graph of
`(precondition, action)` nodes; hybrid with deadlines as fallbacks when a trigger never fires.
*Blocks:* M1 hand-authored plays beyond trivial ones; `chain_depth_penalty` (§5), which is
computed from the play's internal action-dependency graph.

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

### Q-019 · How reliable is heuristic objective/strategy labelling? · `open`
§6 step 2 proposes rule-based labelling of SoccerNet segments ("ended in a shot from a cross
→ wing overload"). Unvalidated. If label noise is high, supervised pretraining learns the
heuristic's mistakes rather than the game.
*Cheap check:* hand-label a few hundred segments and measure agreement.
