# How a play becomes feasible

Everything that decides whether a play can be called right now, in the order the code checks
it. Line numbers are as of this commit. To see every check for every play in a real situation:

```
python scripts/explain_feasibility.py                                  # mid_progression, seed 0
python scripts/explain_feasibility.py --scenario build_up --seed 3 --at 4.0
python scripts/explain_feasibility.py --play third_man_combination --detail
```

This is the self-play path (YAML plays in `plays/`, `soccersim/schema`, `soccersim/ranking`).
The older design-doc prototype in `soccersim/plays/` and `soccersim/constraints/` is a separate,
earlier implementation and is not used by self-play.

## The three ingredients

**1. What the play asks for** (the play's YAML; fields defined in `soccersim/schema/models.py`):

| Field | Meaning | Model |
|---|---|---|
| `phase` | when the play applies: `in_possession`, `transition_attack`, `set_piece` (we have the ball) or `out_of_possession`, `transition_defense` (they do) | `Play`, `models.py:88` |
| `roles` | who the play needs. Each role has `hints` (positions that suit it, e.g. `[CB_near, DM]`), `requires` (minimum capabilities, e.g. `{passing: 0.5}`), `prefers` (soft), `starts_with_ball`, and optionally a `group` (several players) | `Role`, `models.py:28` |
| `triggers` | conditions that must hold to start the play | `Play.triggers` |
| `hard_constraints` | extra conditions that must also hold (checked after the triggers) | `Play.hard_constraints` |
| `cooldown_s` | seconds after the play ends before it can be called again | `Play.cooldown_s` |
| `fallback` | marks the always-available play (`recycle_possession`); it never counts as filling a library gap | `Play.fallback` |

Triggers and hard constraints are written in a small condition language (spec §4.5):
combinators `all`, `any`, `not`, `always`, and the conditions below. Which conditions and
parameters are allowed is checked when a play is loaded, by `check_predicate` in
`soccersim/schema/predicates.py:30` (called from `validate_play`, `soccersim/schema/validate.py:135`).

**2. The current situation**, as one team sees it: `TeamView` in `soccersim/dashboard/team_state.py:39`,
built every tick from the simulator state. It works in the team's attacking frame (always
attacking +x) and provides possession, the ball holder, positions and velocities, player
capabilities and stamina, and the measurements the conditions use:

| Measurement | Where |
|---|---|
| possession (`us`/`them`/loose), ball holder | `team_state.py:64-78` |
| ball side ("near" = the side the ball is on; frozen while the ball is central) | `side_from_ball`, `team_state.py:98` |
| a player's side-relative position (`CB_near`, `W_far`, ...) | `hint_of`, `team_state.py:109` |
| zones (`own_third.center`, `final_third.near_wing`, ...) | `soccersim/dashboard/zones.py` (`zone_mask` :30, `in_zones` :62) |
| defensive lines and their height, offside line | `lines`/`line_x` `team_state.py:143-158`, from `soccersim/dashboard/lines.py` |
| distance to the nearest opponent ("pressure") | `nearest_opponent_dist`, `team_state.py:163` |
| probability a pass reaches its target | `pass_p`, `team_state.py:179`, using the simulator's own pass model `soccersim/sim/passmodel.py:76` (`assess_pass`) |
| pitch control at a point | `pc_at`, `team_state.py:132` (`soccersim/dashboard/pitch_control.py`) |
| expected threat, chance quality (xG) | `xt` :139 (`soccersim/dashboard/xt.py`), `xg_of` :197 |
| players of a team in a zone | `count_in_zone`, `team_state.py:205` |
| recent events (possession won, goal kick, ...) | `soccersim/sim/events.py:58` (`happened`) |

**3. The checker**: `RankingPolicy.rank` and `RankingPolicy.evaluate` in
`soccersim/ranking/selector.py:88-112`, which run the checks below for every library play (and
every generated play) at each decision. Conditions are evaluated by `Evaluator.pred`
(`soccersim/dashboard/evaluator.py:272`), which also resolves roles to players
(`player`, :72), targets (`target`, :189), opponent selectors (`selector`, :87) and anchors
(`anchor`, :116).

## The checks, in order

A play is feasible only if it passes every step; the first failure is recorded as its reason
(you see these reasons in the decision inspector of every replay page and in the logs).

| # | Check | Code | Reason recorded |
|---|---|---|---|
| 1 | **Phase**: the play's `phase` matches whether we have the ball | `phases_for`, `soccersim/ranking/constraints.py:13`; used in `rank` `selector.py:101` | (play skipped) |
| 2 | **Cooldown**: the play didn't end less than `cooldown_s` ago | `in_cooldown`, `constraints.py:21`; set by `notify_end` `selector.py:82` | `cooldown` |
| 3 | **Roles**: every role can be filled by a different player | `assign`, `soccersim/ranking/assignment.py:63` | `no eligible player for role R1`, `ball role but we do not hold the ball`, ... |
| 4 | **Triggers** hold, with the players chosen in step 3 | `triggers_hold`, `constraints.py:25` -> `Evaluator.pred` | `triggers` |
| 5 | **Hard constraints** hold | `hard_gate`, `constraints.py:29` | `hard_constraints[i]` |
| then | feasible plays are **scored** and the best one is called | `score_play`, `soccersim/ranking/scorer.py:22`; `_select`, `selector.py:120` | |

**Step 3 in detail** (`assignment.py:63-128`). For each role slot and each of our players:

- a role with `starts_with_ball` can only be the current ball holder, and nobody else in the
  play may be the holder;
- the goalkeeper can only fill roles that list `GK`, and a `GK`-only role needs the keeper;
- every `requires` capability must be at least its minimum (capabilities: pace, acceleration,
  stamina, passing, vision, crossing, dribbling, first touch, finishing, aerial, tackling,
  positioning, composure);
- otherwise the pairing gets a cost: position fit (`hints` vs the player's side-relative
  position, `hint_cost` :34), how far below the `prefers` levels the player is (`pref_gap` :42),
  how far the player has to travel to the role's first position (`role_start` :50), and fatigue.

The Hungarian algorithm then picks the cheapest one-to-one assignment. If any slot is left
with no eligible player, the play is infeasible. Note the order: **players are chosen first
(cheapest), then the triggers are checked for those players.** A trigger such as
`lane_open: {from: R1, to: {role: R2}}` is tested for the chosen R2 only; a play can fail its
triggers even when a different R2 would have passed.

## The conditions (`Evaluator.pred`, `evaluator.py:272-370`)

| Condition | True when |
|---|---|
| `possession: us\|them` | that team has the ball |
| `has_ball: R1` / `teammate` / `opponent` | that role's player (or any teammate / any opponent) has the ball |
| `ball_in_zone: [zones]` | the ball is in any of the zones (`*` wildcards, side-relative lanes) |
| `role_in_zone: {role, zone}` | that role's player is in the zone |
| `dist: {a, b, lt/gt...}` | distance between two points/players compares as given |
| `ahead_of: {a, b, by}` | a is at least `by` metres further upfield than b |
| `pressure_on: {ref, lt/gt...}` | distance from that player to the nearest opponent (metres) compares as given; small = pressed |
| `lane_open: {from, to, min_p}` | the pass model gives a pass from `from` to `to` at least `min_p` chance of arriving |
| `pc_at: {target, ...}` | our pitch control at the target compares as given |
| `xg: {ref, ...}` | that player's shot quality from where they stand compares as given |
| `line_height: {line, ...}` | a defensive line's height compares as given |
| `count_in_zone: {team, zone, ...}` | number of that team's players in the zone compares as given |
| `goal_side_count: {team, ...}` | number of outfield players goal-side of the ball compares as given |
| `teammates_near: {ref, radius, ...}` | teammates within `radius` of a point compare as given |
| `onside: R1` | that role's player is onside |
| `event: {type, within_s}` | the event (possession won, goal kick ours, ...) happened recently |
| `ball_beyond_line` / `ball_behind_line: {line, by}` | the ball is past (or behind) that opponent/our line |
| `elapsed_s`, `step_elapsed_s` | time since the play / step started (used in steps, success and abort) |
| `game: {score_diff, minute}` | match state |

Comparisons use `lt`, `le`, `gt`, `ge`, `eq`.

## After feasibility

- **Scoring** (`scorer.py:22`): objective and strategy value from `configs/ranking.yaml`, minus
  penalties for risk, fatigue, positional fit, chain depth and assignment cost, plus the critic
  when enabled and a scripted style's bonus. The best score is called (`_select`).
- **Library gap** (`_gap`, `selector.py:114`): no feasible non-fallback play, or the best one
  scores under `generator.threshold` (0.03). That is when the generator is consulted.
- **When decisions happen** (`soccersim/sim/env.py:138-168`): at the start, whenever a play
  ends, on every possession change and restart, and every 2 s as a check for something
  better (switching only if it is better by `preempt_margin`). If nothing is feasible the
  team retries 0.5 s later.
- **Generated plays** go through exactly the same checks (they are added to the candidate
  list in `decide`, `selector.py:130`).
