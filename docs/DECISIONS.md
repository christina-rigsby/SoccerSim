# Decision Log

Newest first. Every entry records the **alternatives that were viable** and a **backtrack
trigger** — the concrete, observable condition that should send us back to one of them. An
alternative recorded without that condition is trivia; the trigger is what makes this log
useful in six months.

Statuses: `active` · `superseded by D-0xx` · `provisional` (implemented to unblock work, not
actually settled — always paired with an `OPEN_QUESTIONS.md` entry).

---

## D-028 · The dashboard is asymmetric: we measure ourselves, we infer the opponent
**Date:** 2026-09-11 · **Status:** `active`

`Dashboard.team_report()` returns measurements only. `Dashboard.opponent_model()` runs
the estimators.

**Rationale:** we chose our own scheme, so "inferring" it would be measuring our own
intent through a noisy proxy. §2 splits the same way — "team state (self)" is a list of
observables, while the opponent model is explicitly the part that "grows over time".

**Alternatives considered viable:**
- *Run the estimators symmetrically.* Cheap, and would give a sanity check (the model
  should recover the scheme we know we are playing). Worth doing as a **test** technique
  rather than as a product feature — noted as a follow-up.
- *Model ourselves only through the book.* Which is what we do; §5's
  `predictability_penalty` and `historical_success_rate` are self-knowledge, and they are
  recorded rather than inferred.

**Backtrack trigger:** we need to know how *legible* our own play is to an opponent —
at which point running our own estimators against ourselves becomes the natural measure
of predictability, and the asymmetry goes.

---

## D-027 · Marking inference needs four signals, not one
**Date:** 2026-09-11 · **Status:** `provisional` (see Q-027)

A defender reads as man-marking only when all four hold: a consistent nearest attacker
(target stability), movement aligned with that attacker (displacement cosine), mean
separation inside a marking radius, and that separation *held steady*.

**Rationale, learned the hard way:** stability and alignment alone reported the zonal
scenario as `MIXED`. A zonal defender *sliding across with the ball* moves nearly
parallel to the ball carrier, so alignment cannot separate the two hypotheses. What
distinguishes them is separation: a marker holds a couple of metres and keeps holding
it, while a zonal defender's distance to any given attacker swings freely as attackers
rotate through the zone. Being close to your man is close to the definition of marking
them, so gating on proximity is principled rather than a patch.

Frames where the target barely moved are not observed at all, rather than counted as
evidence for zonal: a defender who did not move had nothing to track, and treating
that as evidence would let stationary play accumulate a false verdict.

**Alternatives considered viable:**
- *Alignment alone* — tried, insufficient, as above.
- *Voronoi/assignment-based inference* — solve a bipartite matching between defenders
  and attackers each frame and measure how stable the matching is. More principled and
  handles switching marks; heavier, and needs the Hungarian machinery M1 will bring
  anyway.
- *Classifier trained on labelled tracking data.* The real answer eventually (D-007).

**Backtrack trigger:** Q-027 — a zonal defender who sits permanently close to one
attacker is still misread as a marker (2 of 11 in the zonal scenario). If that rate
rises with more realistic movement, move to the assignment-stability formulation rather
than adding a fifth threshold.

---

## D-026 · Estimators are validated against scripted scenarios with planted ground truth
**Date:** 2026-09-11 · **Status:** `active`

`soccersim/scenarios.py` generates snapshot sequences in which the opponent's behaviour
is known by construction, each carrying a `ScenarioTruth`. Tests assert the estimator
recovers it.

**Rationale:** an estimator infers things that are not directly observable, so without
ground truth you can only check that it *runs*. Planting the answer is the only way to
score it.

**Negative controls are half the point.** An estimator that answers "man-marking" to
everything scores perfectly on a man-marking scenario. So `zonal` runs the *identical*
attacker paths with zonal defenders, and `passive_block` runs the *identical* pass
script with no pressing — anything reported there is an artefact of attacker movement or
pass frequency rather than a finding about the opponent.

**This is not the simulator.** It contains a crude constant-speed position stepper
purely to make positions change. No ball physics, no play execution, no decisions. The
real tick loop stays deferred until M1 gives it something to execute (D-011).

**Alternatives considered viable:**
- *A minimal tick-based sim loop.* Realistic motion, but no ground truth about marking or
  triggers — you would have to script those behaviours anyway, making it this plus
  physics, and committing to movement choices M1 has not settled.
- *Wait for real tracking data.* Honest, but M3 is blocked behind M1, so it shelves most
  of §2 indefinitely.

**Backtrack trigger:** the estimators pass every scenario but fail on real tracking data
— which would mean the scenarios are too clean. Expected, and the reason these are a
floor rather than a ceiling.

---

## D-025 · Press triggers are conditional rates with deferred labelling
**Date:** 2026-09-11 · **Status:** `active`

Every pass is entered as a *trial* keyed by `(direction, third)` and labelled pressed or
unpressed once its lookahead window has elapsed, via a pending queue. Triggers are the
keys whose rate exceeds a floor on mature evidence.

**Rationale:** counting presses that followed backpasses mostly measures how common
backpasses are. What matters is `P(press | backpass in the middle third)`, and that
needs the *unpressed* backpasses counted too. Without it, any team that passes backwards
a lot gets diagnosed as pressing on backpasses, and §5's `mismatch_bonus` acts on an
artefact of pass frequency.

Labelling has to be deferred because at the moment a pass happens you cannot yet know
whether a press followed.

The `passive_block` scenario demonstrates the difference: identical pass script, and the
rate for `back/middle` comes out 0.00 on mature evidence — an *evidenced absence*, not a
lack of data.

**Alternatives considered viable:**
- *Count presses per preceding pass type.* Simpler, and wrong for the reason above.
- *Score triggers by lift over the base press rate* (`P(press|X) / P(press)`). Better
  for spotting a mild but real association; harder to threshold, and needs a stable base
  rate.

**Backtrack trigger:** a trigger that matters is diluted because it fires only in a
narrow sub-case the `(direction, third)` key cannot express — then the key needs more
dimensions (score, scoreline, ball height), with the usual cost that finer keys mean
fewer trials each.

---

## D-024 · A stateful observer, with history bounded by match time
**Date:** 2026-09-11 · **Status:** `active`

`MatchObserver` ingests snapshots, derives events from the deltas, segments possessions,
and retains a buffer bounded by *elapsed match time* rather than frame count.

**Rationale:** every M0/M0.5 function is a pure function of one instant, and §2's
opponent model is defined by things that accumulate. Those cannot be fields on
`GameState`, because there is nowhere for them to accumulate. This is the somewhere.

Bounding by time rather than frames means a 10 Hz feed and a 1 Hz feed retain the same
*window of history*, so an estimator's behaviour does not silently depend on sample rate.

**Events are derived, not supplied.** Watching `ball.carrier_id` change recovers passes
and turnovers, and a pass's direction relative to the passing team is exactly what
trigger inference keys on. No action vocabulary needed — which matters, because that
arrives with M1.

Two deliberate strictnesses: a backwards clock raises rather than being tolerated, since
out-of-order replay would silently corrupt every decayed estimate; and a possession's end
position is taken from the last frame *that team held the ball*, not from the turnover
frame, because progress should measure how far they moved the ball rather than where the
opponent happened to win it.

**Alternatives considered viable:**
- *Pure streaming, no buffer.* Smallest footprint, but press-trigger detection genuinely
  needs the seconds before a press began.
- *Unbounded history with periodic batch refits.* Most accurate offline; sits badly with
  a 0.5–1 s per-epoch budget.

**Backtrack trigger:** an estimator needs a window longer than is affordable to buffer.
Then it keeps its own running summary rather than the buffer growing.

---

## D-033 · Offside is judged at the moment of the pass, not at play selection
**Date:** 2026-09-11 · **Status:** `active`

`InstantiatedPlay.violations()` does **not** check offside. The executor checks it when a
ball-releasing step actually fires, against that step's receivers.

**Rationale:** §5 says "any `run_behind`/receiving waypoint beyond the second-last
defender **at the moment of the pass** is invalid". A run beyond the line is perfectly
legal to *make* — you are only offside if the ball is played to you while you are there.
Checking at selection time rejected every counter-attack involving a run in behind, which
is most of them.

M0's `check_offside` docstring flagged this as a snapshot approximation "pending Q-009".
Resolving Q-009 is what made the correct timing expressible, so this closes that caveat.

**Alternatives considered viable:**
- *Check at instantiation* (what M0 did). Cheap, and wrong in the direction that
  discards good plays.
- *Check both, as a warning at selection and a violation at the pass.* More information,
  but a warning nothing consumes is noise.

**Backtrack trigger:** none expected. Note the related fix in D-032: a delivery target
that ignores the offside line makes every cross illegal, which is an anchor problem
rather than a checking problem.

---

## D-032 · Delivery anchors are line-aware; a releasing action's anchor is a ball target
**Date:** 2026-09-11 · **Status:** `active`

Two related corrections, both about what an anchor *means*.

`ActionSpec.releases_ball` now settles whether a step's anchor is where the **ball** goes
or where the **player** goes. `instantiate` only builds a `Waypoint` for player
destinations. Previously every anchored step produced a waypoint, so a crosser was
required to *run to* the near post — and collided with the player attacking it.

`BoxTarget` pulls its depth back to stay level with or behind the second-last defender.
A striker attacking a cross is onside by definition, so a fixed six-yard-box target is
offside against any deep block. Combined with D-033, every cross in the library aborted
until this anchor became line-aware.

**Rationale:** both are the D-003 principle applied more thoroughly. A delivery target is
a *relationship to the defence*, not a fixed spot, and the distinction between "the ball
goes here" and "the player goes here" is information the action vocabulary already had.

**Alternatives considered viable:**
- *Separate `ball_anchor` and `player_anchor` fields per step.* Explicit, but every step
  needs exactly one of them, so the action already determines which.
- *Leave `BoxTarget` fixed and let plays pick the depth.* Pushes an offside calculation
  into every hand-authored play file.

**Backtrack trigger:** a set piece, where offside does not apply from the restart — hence
the explicit `onside=False`.

---

## D-031 · Every step is bounded: timeouts run from eligibility, not activation
**Date:** 2026-09-11 · **Status:** `active`

A step that is eligible but whose trigger has not fired times out just as one that
activated and did not complete.

**Rationale:** without it a play whose trigger condition never materialises waits
forever. D-002's "be willing to abort mid-play and reselect" needs every step to be
bounded, or a single unmet condition hangs the play and nothing reselects. The failure
was found by rehearsing `switch_and_cross`, which sat waiting on a blocked switch pass
until the harness ran out of frames.

The abort reason names the trigger that never fired, which is the diagnostic that makes
an authored play debuggable.

**Alternatives considered viable:**
- *A separate, longer eligibility timeout.* More expressive; two numbers per step to
  tune for no demonstrated benefit.
- *A play-level deadline only.* Simpler, but loses which step actually stalled.

---

## D-030 · Play roles are filled by a greedy stand-in until the assignment solve lands
**Date:** 2026-09-11 · **Status:** `provisional` (see Q-032)

`plays/assignment.py` fills roles greedily, scarcest role first, breaking ties on
practised-role then fit score.

**Rationale:** the real solve is bipartite matching over capability-match edge weights
(D-004), which belongs with the graph and weight-algebra work. A placeholder lets the
whole pipeline run end to end now, and running it surfaced something worth handing over:
**capability fit alone is not enough.** The greedy pass cheerfully assigned a full-back
30 m from the play's first waypoint, and assigned a left winger to a right-flank play,
because nothing in §4's capability-match edge accounts for *where the player currently
is*. The cost matrix needs a positional term — which the kinematic reachability check
already computes.

**Alternatives considered viable:**
- *Hand-authored assignments per play per fixture.* No inference to get wrong, but
  nothing exercises the role layer.
- *Implement Hungarian now.* Would require inventing the cost semantics Q-001 governs.

**Backtrack trigger:** the real solve arrives. Delete this module; everything downstream
takes a plain `{role: player_id}` mapping either way.

---

## D-029 · A play is a triggered dependency graph over spatial anchors
**Date:** 2026-09-11 · **Status:** `active`

A play is data: named play roles (M0.5), actions (§3's vocabulary), **anchors** that
resolve to points against live state, and **triggers** that fire on events. Steps form a
DAG. Anchors, triggers and whole plays round-trip through JSON.

**Rationale — anchors.** This is the mechanism behind D-003, and the direct answer to
"plays must be flexible, not player A from (x1,y1) to (x2,y2)". §3 names four spatial
references and all four are implemented on M0 machinery: maximum pitch-control gain along
a flank, the midpoint of a measured line gap, N metres behind the last-defender line in a
channel, and the edge of a cover shadow. Because geometry is recomputed each epoch, one
play generalises across opponent shapes instead of needing a variant per formation.

**Rationale — triggers (resolving Q-009).** §3 requires event triggers, not clock times,
and M0's `Waypoint.deadline` was explicitly a placeholder to replace (D-014). Waypoint
deadlines are now *derived* from the graph — the sum of timeouts along the longest path to
a step — so the kinematic check asks the right question: can this player get there before
the play would give up on them? That also links chain depth to feasibility, which is why
§5 penalises depth.

**Rationale — the DAG.** §5 defines `chain_depth_penalty` as computed "directly from the
play's internal action-dependency graph", so the graph has to be the primary structure and
the longest path *is* the chain depth. A flat step list could not express it. The same
graph yields `single_ball` for free: two ball-touching steps conflict exactly when neither
is an ancestor of the other, since then nothing orders them. That check caught a real
error in the hand-authored three-pass counter, where the passer's and receiver's steps
were siblings.

Measured on the shipped library, chain depth tracks football intuition: presses are depth
2 and parallel, the direct counter 3, the three-pass counter 5.

**No weights.** Structural metrics are computed; turning them into penalties waits for
Q-001 (D-022's cut line applied again).

**Alternatives considered viable:**
- *Python predicate objects instead of a data registry.* Less machinery, but plays could
  not then be authored, diffed or generated as data.
- *Parameterised play templates.* Simplest to author; hides the dependency graph that
  §5 needs, and a new play shape means new code.
- *Raw coordinates with per-formation variants.* Trivial to debug, and the thing D-003
  exists to avoid.

**Backtrack trigger:** the anchor or trigger vocabulary stops being expressive enough and
plays start needing escape hatches into Python. Adding a kind to the registry is cheap;
needing arbitrary code is the signal that data-driven was the wrong call.

---

## D-023 · Every inferred value carries its own maturity
**Date:** 2026-09-11 · **Status:** `active`

`Estimate` wraps every inferred quantity with a decayed observation count and a maturity
threshold. `value` is always readable for inspection; `mature_value` returns `None` until
the threshold is crossed; `require_mature()` raises with the shortfall.

**Rationale:** §5's `mismatch_bonus` feeds opponent-model data straight into play
ranking. If the model is confidently wrong after one possession, plays get chosen on
noise — and because the chosen play then generates more observations of its own
choosing, the error is self-reinforcing. A bare point estimate makes that impossible to
guard against.

The API is shaped so the safe path is the obvious one: the natural
`if estimate.mature_value is not None` is correct by default, with no discipline required
from the caller.

Observations are **decayed, not counted**: a team that pressed in the first half and sat
deep in the second should not be described by the average of the two. A consequence worth
noting is that a stale estimate *stops* being mature, which is intended — old evidence
should not stay actionable.

**Alternatives considered viable:**
- *Bayesian posteriors per estimate.* Genuine uncertainty intervals, and they compose
  properly. Heavier, and the priors are themselves unknown (Q-008 asks what they should
  be). The better destination once there is data to set priors from.
- *Point estimates only.* Simplest; nothing then stops a one-possession sample driving a
  play choice.

**Backtrack trigger:** a consumer needs to weigh two estimates of differing confidence
against each other, rather than just gate on them. A count cannot express that
faithfully — move to posteriors.

---

## D-022 · Role fit is a raw `[0, 1]` quality reading, not a cost or a probability
**Date:** 2026-09-11 · **Status:** `active`

`role_fit` returns a weighted mean of normalised attributes. It is explicitly **not** a
cost, a utility, or `P(success)`.

**Rationale:** the weight algebra is unresolved (Q-001). Turning fit into an edge weight
now would pick a semantics by accident — the exact failure mode these documents exist to
prevent. A unitless quality reading is the most that can honestly be computed before
Q-001 closes, and mapping it onto whatever algebra wins is a later, explicit step.

**Alternatives considered viable:**
- *Emit a cost directly* (`1 - fit`, or `-log(fit)`). Convenient for the Hungarian solve,
  but each of those IS a choice of algebra.
- *Emit a calibrated success probability.* The right long-term answer if Q-001 lands on
  log-probabilities, but it needs outcome data to calibrate against.

**Backtrack trigger:** Q-001 closes. At that point add a conversion at the boundary
rather than changing what `role_fit` returns, so the fit score stays inspectable.

---

## D-021 · Only our own players have authored attributes
**Date:** 2026-09-11 · **Status:** `active`

`PlayerState.attributes` is `Attributes | None`. Home players get theirs from a roster
file; away players carry `None`, and `role_fit` raises an explanatory error rather than
scoring them. `parse_roster` refuses a roster whose `team` is `away`.

**Rationale:** we know our own squad's ratings because we wrote them down. An opponent's
have to be *inferred from observed play*, which is Q-008 and M2's job. Letting away
players default to 50s would make every opponent an identical average team while looking
like real data — worse than an explicit gap, because it silently succeeds.

**Alternatives considered viable:**
- *Default opponents to league-average attributes.* Simple, and arguably a reasonable
  prior. Rejected for now because an uninformative prior that reads as data is how
  modelling errors get laundered; revisit once M2 can say how confident the inference is.
- *Require attributes on every player.* Would force fabricating opponent data.

**Backtrack trigger:** M2 produces attribute estimates with usable uncertainty. Then
away players carry inferred attributes plus a confidence, and the `None` case disappears.

---

## D-020 · `min_role_coverage` gates on per-attribute minimums, not on a fit threshold
**Date:** 2026-09-11 · **Status:** `active`

Each `PlayRole` carries sparse `minimums` in native units (0–100 for attributes, SI for
physical). Coverage fails when no available player clears every one.

**Rationale:** a threshold on the fit score would need the score to mean something, which
drags Q-001 into a hard constraint that does not otherwise depend on it. Per-attribute
minimums are also far more interpretable — "a target forward needs heading ≥ 58" is a
statement you can argue with, where "fit ≥ 0.63" is not — and they produce an actionable
diagnostic: which attribute fell short, and by how much.

Comparison happens on the normalised scale, so attributes where lower is better
(`reaction_time`) invert automatically and "meets the minimum" always means "is at least
this good". Minimums are validated against their scale at construction, because a
physical minimum above the reference ceiling would clip to 1.0 and silently pass everyone.

**Alternatives considered viable:**
- *Threshold on the fit score.* One number per role instead of several. Rejected per above.
- *No hard coverage check; let bad fits be expensive.* This is what §5 explicitly rules
  out: coverage failure is infeasibility "regardless of assignment cost".

**Backtrack trigger:** minimums prove too blunt — e.g. a role genuinely needs "either
great pace or great positioning", which a conjunction of floors cannot express. Then the
gate becomes a small predicate rather than a dict.

---

## D-019 · Attributes are 0–100 and lean; physical capability stays SI
**Date:** 2026-09-11 · **Status:** `active`

Thirteen technical/mental attributes on a 0–100 scale in `domain/attributes.py`. Physical
capability stays in `CapabilityProfile` in SI units. `PHYSICAL_RANGES` projects the SI
values onto 0–1 so role matching can read both.

**Rationale:** the kinematics layer does real physics with speed and acceleration, so
those must stay in metres and seconds — converting a 0–100 "pace" rating into m/s would
mean inventing a mapping and then computing arrival times from a made-up number. The
0–100 attributes have no physical meaning and are only ever compared with each other, so
a conventional game-style scale is fine and is much easier to hand-author.

The set is lean on purpose, and a test enforces that **every attribute is read by at
least one role in the catalogue**. An attribute with no consumer is a number that invites
false precision and drifts out of date.

**Alternatives considered viable:**
- *~30 FM-style attributes.* More expressive; most would have no consumer.
- *~5 attributes.* Cannot distinguish a target forward from a poacher, which is the whole
  discrimination role matching exists to make.
- *One unified 0–100 scale including physical.* Loses real units where they matter.

**Backtrack trigger:** a play needs a distinction the current 13 cannot express. Add the
attribute *and* the role that reads it in the same change, so the invariant holds.

Also recorded: fatigue degrades **physical** inputs to fit (extending D-006 into role
matching, so a tired player is genuinely worse at a pace-dependent role) but not technical
ones. That asymmetry is a simplification, tracked as Q-021.

---

## D-018 · Positional slot and play role are separate concepts
**Date:** 2026-09-11 · **Status:** `active`

`PositionalRole` (GK, LB, RCM, …) is where a player lines up. `PlayRole`
("overlap_runner", "target_forward") is a job a play needs someone to do. They are
different fields with different types, and matching is by capability, not by label.

**Rationale:** this is what makes plays generalise. The Overlap play needs someone who can
overlap and cross; a right-back, right-midfielder or even a right centre-mid might be the
best answer on the day. Tying play roles to slots would mean authoring a variant of every
play per formation — the same trap D-003 avoids for waypoints.

A consequence worth stating plainly, because it looks like a bug and is not: a holding
midfielder can outscore both centre-backs at `ball_playing_defender`. That is the model
working.

One **hard** exception: `required_slots` gates a role to particular slots, used only where
exclusivity is a rule of the game rather than a preference. In practice that is the
goalkeeper alone. Without it an outfielder with good passing and positioning outranks the
actual keeper at `sweeper_keeper`, and no attribute minimum can prevent it because the
shortfall is not in any attribute. `affinities` remains purely advisory.

**Alternatives considered viable:**
- *One `role` field, as before.* Simplest, and what M0 shipped. Cannot express "who should
  make this run" at all.
- *Hand-tag each player with the roles they can fill.* Matches how a coach thinks, but
  needs a manual pass per new play and cannot rank two eligible players.
- *Derive fit purely from attributes, no familiarity tracking.* Then §5's
  `role_familiarity` soft constraint has nothing to read and cannot be implemented; hence
  the `practised_roles` set alongside derived fit.

**Backtrack trigger:** none expected. If the catalogue grows unmanageable, the fix is
composing roles from smaller requirement fragments, not recombining the two concepts.

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
