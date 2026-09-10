# Decision Log

Newest first. Every entry records the **alternatives that were viable** and a **backtrack
trigger** — the concrete, observable condition that should send us back to one of them. An
alternative recorded without that condition is trivia; the trigger is what makes this log
useful in six months.

Statuses: `active` · `superseded by D-0xx` · `provisional` (implemented to unblock work, not
actually settled — always paired with an `OPEN_QUESTIONS.md` entry).

---

## D-017 · Turn cost in `time_to_point` = perpendicular speed / max_accel
**Date:** 2026-09-10 · **Status:** `provisional` (see Q-015)

Arrival time charges `‖v − max(v·û, 0)·û‖ / max_accel` to redirect existing momentum, then
runs a trapezoidal profile from the target-aligned speed component. A player sprinting away
from the target pays the full cost of arresting their velocity.

**Rationale:** cheap, vectorises over a grid, continuous, and gets the sign of the effect
right (momentum away from a point costs time). That is enough for the qualitative "who owns
this space" question.

**Alternatives considered viable:**
- *Ignore velocity entirely (pure distance).* Rejected — makes transition moments, which is
  exactly where counter-attacking strategies live, indistinguishable from settled play.
- *Curved-path / bicycle model with speed loss in the turn.* More faithful, but needs a
  turn-radius parameter per player that we cannot yet estimate.
- *Fitted arrival-time model from tracking data.* The right long-term answer; needs SoccerNet
  ingest, which is M3.

**Backtrack trigger:** control fields visibly disagree with intuition on transition
snapshots, or arrival-time error against real tracking data exceeds ~0.3 s.

---

## D-016 · Passing lanes use constant ball speed
**Date:** 2026-09-10 · **Status:** `provisional` (see Q-007)

`assess_lane` compares defender arrival times against a ball travelling at a fixed speed
along a straight 2-D segment.

**Rationale:** the foundation layer needs *a* lane test to build the interface against, and
constant speed is the version with no unknown parameters.

**Alternatives considered viable:**
- *Per-pass-type models* (`ground` with rolling deceleration, `lofted` ballistic, `through`
  weighted into space) — matches §3's action vocabulary and is where this must end up.
- *Sampled pass-outcome probability* (Spearman-style), which would fold lane assessment and
  pitch control into one model.

**Backtrack trigger:** the first time a lofted or through ball needs evaluating — the 2-D
occlusion test is simply wrong for a ball travelling over a defender's head, not just
imprecise.

---

## D-015 · xT is an uncalibrated analytic prior
**Date:** 2026-09-10 · **Status:** `provisional` (see Q-006)

`AnalyticThreatSurface` returns `exp(−d/18) · 1/(1 + (|y|/16)²)` — monotone toward goal,
symmetric about the centre line, bounded in (0, 1]. Exposed behind a `ThreatSurface`
protocol so a fitted grid can replace it without touching callers.

**Rationale:** the shape is what downstream code needs to be written against; the magnitudes
are not needed until coefficients get tuned.

**Alternatives considered viable:**
- *Fitted from SoccerNet* — the real answer, blocked behind data ingest.
- *A published xT grid* (e.g. Karun Singh's) — quick, credible, but licence and
  pitch-convention mapping need checking.
- *Goal-angle-based analytic prior* (angle subtended by the posts) — more principled than the
  `|y|` term, but degenerate at the goal mouth.

**Backtrack trigger:** anyone proposes to tune soft-constraint coefficients (Q-014). Do not
tune against this surface.

---

## D-014 · `Waypoint` is the feasibility interface, defined ahead of `Play`
**Date:** 2026-09-10 · **Status:** `active`

Feasibility checks consume `Waypoint(player_id, target, deadline, action)` rather than a full
`Play`. Plays will later compose lists of waypoints.

**Rationale:** the hard kinematic constraints (§5) are testable against a single waypoint and
do not need the ranking design settled. Waiting for `Play` would block foundation work behind
Q-001 and Q-009, which are the two least-settled questions in the project.

**Alternatives considered viable:**
- *Wait for the `Play` type.* Rejected — couples M0 to unresolved M1 design.
- *Check against raw `(player, point, time)` tuples.* Same thing with less documentation.

**Known limitation:** `deadline` is an absolute offset in seconds. §3 requires
event-triggered waypoints (Q-009), so this field is a placeholder to be **replaced**, not
extended.

**Backtrack trigger:** none expected; this is subsumed when Q-009 closes and the trigger
representation lands.

---

## D-013 · Pitch control = sigmoid over time-to-intercept advantage
**Date:** 2026-09-10 · **Status:** `provisional` (see Q-005)

`control = σ(λ · (t_def_best − t_att_best))` where arrival times come from
`kinematics.time_to_point` and λ = 1.5 per second.

**Rationale:** captures velocity (unlike Voronoi), needs no calibration data (unlike
Spearman), vectorises cleanly over a grid, and reuses the same arrival-time function as the
kinematic hard constraint — so the space layer and the constraint layer cannot disagree about
whether a player can reach a point.

**Alternatives considered viable:**
- *Plain distance Voronoi.* Cheaper and fully parameter-free, but momentum-blind.
- *Full Spearman pitch control* with pass-outcome probability. The most faithful, but needs
  pass-completion data to calibrate.

**Backtrack trigger:** λ proves un-tunable, or the field disagrees with real tracking data in
a way a single sharpness constant cannot fix — then move up to Spearman rather than patching.

---

## D-012 · Coordinate system: metres, centre origin, attacking +x
**Date:** 2026-09-10 · **Status:** `active`

105 × 68 m pitch. `x ∈ [−52.5, 52.5]`, `y ∈ [−34, 34]`, origin at the centre mark. A team's
`attacking_direction` is `+1` or `−1` and multiplies `x`.

**Rationale:** signed `y` makes centrality and mirror-symmetry assertions trivial (`f(y) ==
f(−y)`), which is how most of the geometry tests are written. Signed attacking direction means
one code path handles both halves.

**Alternatives considered viable:**
- *Corner origin, `x ∈ [0, 105]`.* Matches most tracking-data providers, so ingest will need a
  conversion either way — but loses free symmetry tests.
- *Normalised `[0,1]²`.* Resolution-independent, but kinematics needs real metres and seconds,
  so it would mean converting on every call.

**Backtrack trigger:** none likely — conversion at the data-ingest boundary is a few lines.

---

## D-011 · Static snapshot rendering, no tick loop yet
**Date:** 2026-09-10 · **Status:** `active`

`viz/render.py` draws a single game state with optional pitch-control, lane, and threat
overlays. No time-stepping.

**Rationale:** the space layer's failure mode is subtly wrong geometry, which an image catches
and numeric assertions on synthetic cases do not. A tick loop would force movement-physics
decisions before there is any scoring function to drive movement.

**Alternatives considered viable:**
- *Tick loop + animation now.* Would validate the replanning cadence (Q-012) earlier.
- *Tests only.* Fastest, but spatial bugs stay invisible.

**Backtrack trigger:** M1's end-to-end play selection lands — at that point a loop is needed
to see whether abort-and-reselect (D-002) behaves.

---

## D-010 · First implementation slice = foundation layer only
**Date:** 2026-09-10 · **Status:** `active`

Domain model, space/geometry layer, and kinematic feasibility. No ranking graph, no plays, no
ML.

**Rationale:** directly follows the design doc's own build order (§6, "Suggested build
order"): everything downstream depends on a good "is this good for us right now" scoring
function, so building the ranking graph first would mean writing edge weights against
geometry that does not exist.

**Alternatives considered viable:**
- *Thin vertical slice through modules 1+2* — one full Objective→Play selection running
  end-to-end. More motivating, but most of it would be provisional pending Q-001.

**Backtrack trigger:** n/a — superseded naturally by M1.

---

## D-009 · Python 3.11 + numpy / scipy / matplotlib
**Date:** 2026-09-10 · **Status:** `active`

**Rationale:** the geometry layer is grid math (numpy), the assignment step is
`scipy.optimize.linear_sum_assignment`, and module 3 is entirely Python-ecosystem
(SoccerNet, torch, GNNs). One language end to end, no bridge.

**Alternatives considered viable:**
- *TypeScript / Node.* Better if the endpoint is a browser-rendered simulation, but forces a
  Python bridge or reimplementation for module 3.
- *Rust core + Python bindings.* Fastest per-epoch replanning, cleanest physics, but much
  slower to prototype while the design is still moving.

**Backtrack trigger:** per-epoch replanning misses the 0.5 s budget (Q-012) after the obvious
numpy vectorisation is already done. Then move the space layer to a Rust core and keep the
ranking and ML layers in Python.

---

## D-008 · Build order: space layer and critic before generator
**Date:** from design doc §6 · **Status:** `active`

**Rationale:** the doc's own reasoning — the ranking system's constraint checks, the
generator's candidate ranking, and even a naive rule-based module-3 fallback all depend on
having a good "is this good for us right now" scoring function.

**Alternatives considered viable:** *ranking graph first* (more visible progress, but weights
would be written against absent geometry); *generator first* (most novel, but nothing to
evaluate its output with).

**Backtrack trigger:** none — this is a sequencing decision, not a design one.

---

## D-007 · SoccerNet as the prototyping data source
**Date:** from design doc §6 · **Status:** `active`

SoccerNet-GSR for structured per-frame game states, SoccerNet-Tracking for raw trajectories,
Action Spotting for play-boundary segmentation.

**Rationale:** open and adequate for prototyping.

**Known limitation, from the doc:** broadcast-camera-derived tracking has calibration noise
and misses off-screen players. Treat as noisy-continuous, not ground truth.

**Alternatives considered viable:** *Skillcorner* or *StatsBomb 360* — professional-grade
full-pitch tracking.

**Backtrack trigger:** critic accuracy plateaus and error analysis points at tracking noise
or missing off-screen players rather than model capacity.

---

## D-006 · Fatigue degrades capability, it does not add a penalty
**Date:** from design doc §5 · **Status:** `active`

Fatigue reduces the effective capability score on the RoleRequirement→Player edge.
Implemented now as `PlayerState.effective_capability()`, which scales `max_speed` and
`max_accel` by stamina.

**Rationale:** this makes fatigue automatically penalise *high-sprint-demand roles for tired
players specifically*, rather than penalising tired players uniformly regardless of what is
being asked of them.

**Alternatives considered viable:** *flat additive soft penalty per unit of fatigue* — simpler
but role-blind, so it cannot express "this player is too tired to be the overlap runner but
fine as the holding midfielder."

**Backtrack trigger:** none expected. Note the degradation curve itself
(`FATIGUE_FLOOR = 0.75`) is a guess.

---

## D-005 · Hard/soft constraint split, hard constraints as a pre-filter
**Date:** from design doc §5 · **Status:** `active`

Hard constraints prune (binary), soft constraints penalise (feed the weight sum). Hard checks
run before path weights or the assignment solve.

**The classifying test, from the doc:** *is violating this ever acceptable if the alternative
is worse?* Yes → soft. No → hard.

**Rationale:** the assignment solve is the expensive step; pruning infeasible plays first
keeps it off the hot path.

**Alternatives considered viable:** *all-soft with very large penalties* — one uniform
mechanism, and it degrades gracefully when every option is bad. But it means paying full
scoring cost for plays that are physically impossible, and large penalties interact badly with
any probabilistic weight semantics (Q-001).

**Backtrack trigger:** situations arise where *every* play is hard-infeasible and the system
has nothing to return. A fallback ordering over infeasible plays would then be needed —
possibly by relaxing hard constraints into very large soft penalties as a last resort.

---

## D-004 · Two-stage scoring: path weight + assignment solve
**Date:** from design doc §4 · **Status:** `active`

Stage 1 sums Objective→Strategy→Play→Constraint path weights. Stage 2 solves the best
one-to-one mapping of available players onto role slots via bipartite matching
(Hungarian / Kuhn–Munkres).

**Rationale:** a play needs a *set* of players filling distinct role slots simultaneously.
That is an assignment problem, not a path problem — a single path through the graph cannot
express "these eleven players, each in a different slot, at once."

**Alternatives considered viable:** *single shortest path over the whole graph* — rejected on
the above; *greedy role filling* — much cheaper but demonstrably suboptimal, and Hungarian at
~11 roles is trivial anyway.

**Backtrack trigger:** none for the structure. If assignment ever needs to express constraints
*between* slots (e.g. "the overlap runner must be on the same flank as the winger"), plain
bipartite matching is insufficient and this becomes a constrained assignment problem.

---

## D-003 · Waypoints are defined against the pitch-control layer, not raw coordinates
**Date:** from design doc §3 · **Status:** `active`

Waypoints reference geometry — "point of maximum pitch-control gain along the flank",
"midpoint of the CB–fullback gap", "N metres behind the last defender's line", "edge of the
nearest defender's cover shadow" — rather than fixed pitch coordinates.

**Rationale:** plays then generalise across opponent formations automatically, since the
geometry is recomputed live each epoch.

**Alternatives considered viable:** *raw or opponent-relative coordinates* — trivial to author
and debug, but every play would need a variant per opponent shape.

**Backtrack trigger:** geometry recomputation dominates the per-epoch budget (Q-012). Mitigate
by caching the control field per epoch and sharing it across all candidate plays before
abandoning the approach.

---

## D-002 · Receding-horizon replanning; abort mid-play is allowed
**Date:** from design doc §1 · **Status:** `active`

Re-evaluate feasibility and ranking every ~0.5–1 s of simulated time, or on trigger events.
Plans are not one-shot.

**Rationale:** an opponent's response invalidates a plan faster than the plan completes.
Committing to a play that has stopped making sense is worse than switching.

**Alternatives considered viable:** *one-shot commit to a selected play* — simpler, no
hysteresis problems, and arguably more realistic for genuinely rehearsed set-piece routines.

**Backtrack trigger:** oscillation — the system thrashing between two plays on consecutive
epochs without executing either. The fix would be hysteresis or a commitment bonus rather
than abandoning replanning outright. Also see Q-013: aborting interacts badly with
`historical_success_rate` and that interaction is unresolved.

---

## D-001 · Three modules, one selection mechanism
**Date:** from design doc §1 · **Status:** `active`

Generated plays are inserted into the *same* ranking graph as new Play nodes and compete in
the same pass as pre-defined plays. "Is this novel play good" reduces to "does it outrank the
best pre-defined play."

**Rationale:** one selection mechanism, not two branches with a meta-rule arbitrating between
them.

**Alternatives considered viable:** *separate selection branch for generated plays*, with an
explicit policy for when to trust the generator. Less elegant, but it does not require the
critic and the hand-authored weights to share a scale.

**Backtrack trigger:** Q-003 proves intractable — i.e. critic scores cannot be calibrated
against hand-authored edge weights well enough for a fair comparison. Symptom: generated plays
either always win or never win, regardless of situation.
