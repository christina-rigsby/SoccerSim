# SoccerSim

A soccer play-selection simulation. Given the state of a match, decide what to do next.

The design is three modules with a replanning loop tying them together:

1. **Information dashboard** — team state, opponent model, game state, and a live
   space/geometry layer.
2. **Play ranking system** — a weighted graph over objectives, strategies, plays,
   constraints, and players. Path weight plus a player-to-role assignment solve ranks
   candidate plays.
3. **AI/ML play generator** — comes online when no pre-defined play scores above
   threshold, and inserts its candidates into the *same* ranking graph, so there is one
   selection mechanism rather than two.

Full design in [`docs/soccer_simulation_design.md`](docs/soccer_simulation_design.md).

## Where the project is

**M0 (space and feasibility foundation), M0.5 (player roles and matching), and most of
M2 (the information dashboard) are built.** The ranking graph — module 2 — is not.

That order is deliberate: the ranking system's constraint checks, the generator's
candidate ranking, and even a naive rule-based fallback all depend on having a
trustworthy "is this good for us right now" spatial layer. Writing edge weights before
that exists means writing them against geometry that does not.

| What exists | Module |
|---|---|
| Pitch geometry, players, ball, game state, waypoints | `soccersim/domain/` |
| Arrival-time model (trapezoidal + turn cost) | `soccersim/kinematics.py` |
| Pitch control, passing lanes, cover shadows, expected threat | `soccersim/space/` |
| Hard constraints: reachability, bounds, offside, separation | `soccersim/constraints/` |
| matplotlib debug renderer | `soccersim/viz/` |
| Attributes, positional slots, play roles, fit scoring | `soccersim/domain/{attributes,roles}.py` |
| Roster loading; `eligibility` and `min_role_coverage` | `soccersim/domain/roster.py`, `soccersim/constraints/roles.py` |
| Match observer, possession segmentation, derived events | `soccersim/dashboard/observer.py` |
| Single-frame measurements (block, line, pressure, zones) | `soccersim/dashboard/measurements.py` |
| Marking-scheme and pressing inference, with confidence | `soccersim/dashboard/{marking,pressing,estimate}.py` |
| Our own play-usage and success-rate book | `soccersim/dashboard/book.py` |
| Scripted scenarios with planted ground truth | `soccersim/scenarios.py` |

## Three documents worth reading before writing code

The design doc is a snapshot of thinking. These three are the working record, and the
project depends on them staying current:

- **[`docs/OPEN_QUESTIONS.md`](docs/OPEN_QUESTIONS.md)** — what is genuinely unsettled.
  Several existing modules make *provisional* choices to unblock progress; each is
  flagged, and building on one without reading it is how a placeholder becomes load-
  bearing by accident.
- **[`docs/STATUS.md`](docs/STATUS.md)** — task and milestone state.
- **[`docs/DECISIONS.md`](docs/DECISIONS.md)** — every design decision, the alternatives
  that were viable, and a **backtrack trigger** for each: the observable condition that
  should send us back to an alternative.

The most important thing to know before extending anything: **the expected-threat
surface is an uncalibrated placeholder** (D-015 / Q-006). Its shape is right; its
magnitudes are meaningless. Do not tune anything against it.

## Setup

```bash
pip install -e ".[dev]"
```

## Running

```bash
pytest                              # 403 tests
python scripts/demo_snapshot.py     # writes out/{kickoff,wing_overload,counter_attack}.png
python scripts/validate_roster.py   # validates the squad, prints role coverage
python scripts/dashboard_report.py  # scores the opponent model against known ground truth
```

Then **look at the PNGs**. The space layer's characteristic failure is subtly wrong
geometry — a control field that is mirrored, offset, or momentum-blind while still
producing plausible-looking aggregate numbers. Assertions catch regressions; images
catch that. What to check is documented in `scripts/demo_snapshot.py`.

## Your squad lives in a data file

`data/rosters/home.json` is **a placeholder meant to be replaced.** Edit it and run
`python scripts/validate_roster.py`, which validates the file and prints which play
roles the squad can fill, how deep, and — for anything uncovered — who came closest and
by how much.

Two things about that file are load-bearing:

- **Attributes are 0–100 with no physical meaning; physical values are SI.** The split is
  deliberate (D-019): the kinematics layer does real physics with speed and acceleration,
  so those stay in metres and seconds. Omit a `physical` block and the player inherits
  their positional archetype.
- **Only your own players get a roster.** An opponent's attributes have to be *inferred*
  from observed play (Q-008), so away players carry `attributes=None` and role matching
  refuses to score them rather than quietly assuming a league-average 50 (D-021).

## Two kinds of role, and why

`PositionalRole` is where a player lines up (RB, LCM). `PlayRole` is a job a play needs
someone to do (`overlap_runner`, `target_forward`). Matching is by capability, not by
label, which is what lets one Overlap play work whoever is best placed to make the run
(D-018).

A consequence that looks like a bug and isn't: a holding midfielder can outscore both
centre-backs at `ball_playing_defender`. That's the decoupling working. The one hard
exception is the goalkeeper, gated by `required_slots`, because that exclusivity is a
rule of the game rather than a tactical preference.

**What this layer deliberately does not do:** build the Hungarian cost matrix. Role fit
is a raw `[0, 1]` quality reading, explicitly not a cost or a probability (D-022), because
the weight algebra is still unresolved (Q-001). Coverage — "is this play possible with
this squad at all" — needs no weight semantics and works today. Ranking candidates
against each other does, and waits.

## How the dashboard is verified

The space layer is verified by eye (look at the PNGs). The opponent model cannot be — it
infers things that are not directly observable, so "does the output look plausible" is
worthless. Instead `soccersim/scenarios.py` plants known behaviour and
`scripts/dashboard_report.py` scores what the estimators recover:

```
man_marking     scheme MAN, 8/8 assignments recovered exactly
zonal           scheme ZONAL, 13% man-share against a 60% bar
backpass_press  P(press | back/middle) = 1.00, P(press | forward/middle) = 0.29
passive_block   identical pass script, no triggers, rates 0.00 on mature evidence
```

**The negative controls carry as much weight as the positive ones.** An estimator that
answers "man-marking" to everything scores perfectly on a man-marking scenario. So the
zonal scenario runs *identical* attacker paths, and the passive scenario runs an
*identical* pass script — anything reported there is an artefact rather than a finding.

Two results worth reading carefully. `P(press | forward/middle) = 0.29` is not zero,
because defenders who just pressed a backpass are still near the ball when the next pass
goes forward; `MIN_TRIGGER_RATE` excludes it while admitting the 1.00, which is the
conditional-rate design doing its job. And in the zonal scenario 2 of 11 defenders are
still misread as markers (Q-027) — quantified rather than tuned away, because tightening
thresholds until one scenario came out clean would be fitting to the test.

## Nothing can act on a guess by accident

Every inferred value is an `Estimate` carrying decayed observation counts and a maturity
threshold. `value` is always readable for inspection; **`mature_value` returns `None`
until there is enough evidence.** The safe path is the obvious one, which matters because
§5's `mismatch_bonus` feeds opponent-model data straight into play ranking — and a model
that is confidently wrong early picks plays that generate more evidence of its own
choosing (D-023).

Evidence is decayed rather than counted, so a stale estimate stops being mature. That is
intended: a team that pressed in the first half and sat deep in the second should not be
described by the average.

## The one function to understand first

`soccersim/kinematics.py::time_to_point` — "how long until this player can be standing
on that spot?"

Both the pitch-control field and the `max_speed` hard constraint call it. That is on
purpose: the space layer and the constraint layer then cannot disagree about whether a
player can reach a point. The cost is that systematic error there biases everything
downstream in the same direction, which is why it is pinned to closed-form values in
`tests/test_kinematics.py` rather than to its own previous output.

## Conventions

- **Coordinates** (D-012): metres, origin at the centre mark, `x ∈ [-52.5, 52.5]`,
  `y ∈ [-34, 34]`. A team's `attacking_direction` is `+1` or `-1` and multiplies `x`,
  so one code path serves both halves. Home attacks `+x` in every fixture.
- **Fatigue** (D-006) degrades capability rather than adding a penalty, so a tired
  player is automatically a poor fit for sprint-heavy roles specifically, rather than
  being penalised uniformly whatever they are asked to do.
- **Hard vs. soft constraints** (D-005) split on one test: *is violating this ever
  acceptable if the alternative is worse?* Yes → soft (a penalty). No → hard (a prune).
