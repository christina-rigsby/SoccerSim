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

**M0 — the space and feasibility foundation — is built.** Nothing above it is.

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
pytest                              # 151 tests
python scripts/demo_snapshot.py     # writes out/{kickoff,wing_overload,counter_attack}.png
```

Then **look at the PNGs**. The space layer's characteristic failure is subtly wrong
geometry — a control field that is mirrored, offset, or momentum-blind while still
producing plausible-looking aggregate numbers. Assertions catch regressions; images
catch that. What to check is documented in `scripts/demo_snapshot.py`.

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
