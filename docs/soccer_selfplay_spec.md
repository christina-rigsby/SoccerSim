# Soccer Simulation: Self-Play Play-Generation System — Implementation Spec

**Audience:** Claude (coding). This document is the implementation spec. Build it incrementally, milestone by milestone (Section 14). Do not start ML work (Module 3) until the simulator, play executor, and ranking loop run end-to-end with scripted plays.

**Companion document:** if `soccer_simulation_design.md` (the architecture design doc) is provided alongside, use it for background. Where the two disagree on implementation details, this spec takes precedence.

---

## 1. Goal

Build a system that selects and executes soccer plays against a dynamic opponent in a simulator. It has three modules:

1. **Module 1 – Information Dashboard:** team state, opponent model, game state, and a geometry layer (pitch control, passing-lane availability, expected threat).
2. **Module 2 – Play Ranking:** filters candidate plays by hard constraints, assigns players to play roles (Hungarian algorithm), and ranks plays by combined score.
3. **Module 3 – AI/ML Play Generator:** generates new plays when no pre-defined play fits well. Generated plays are inserted into Module 2's candidate set and ranked in the same pass as library plays.

Module 3 is trained with **self-play**. Both teams run the full stack against each other in the simulator, starting from a hand-authored play library (Section 6). Every decision and its outcome is logged. That data trains:

- a **critic** (value of a play in a state),
- a **response model** (how the opponent reacts to a play),
- a **generator** (proposes new plays), fine-tuned with RL inside a league of opponents.

The analogy to AlphaZero is as follows. Module 2 ranking plays the role of search. The generator is the policy prior. The critic is the value network.

---

## 2. Tech stack and principles

- Python 3.11+. Tooling: `uv` or `pip` with `pyproject.toml`, `pytest`, `ruff`, and type hints throughout.
- NumPy for the simulator and geometry. Vectorize pitch control and the pass models, because they are the hot paths.
- `pydantic` v2 for the play schema. `PyYAML` for play files.
- `scipy.optimize.linear_sum_assignment` for role assignment.
- PyTorch plus PyTorch Geometric for Module 3.
- `pyarrow` (Parquet) for self-play logs.
- `multiprocessing` for parallel self-play workers. Keep the simulator single-threaded per episode.
- Matplotlib (or a small static HTML exporter) for the replay viewer.

**Principles:**
- **Deterministic given a seed.** All randomness goes through an injected `np.random.Generator`.
- **Everything config-driven** (YAML in `configs/`). No magic numbers buried in code. The numbers in this spec are initial guesses meant to be tuned.
- **The simulator is abstracted behind an interface** so a Google Research Football adapter can be added later (M10).
- **Speed target:** at least 20× real time per core for 11v11 at 10 Hz. Profile early.

---

## 3. Coordinate system and conventions

- Pitch is 105 × 68 m. Origin at the center spot. x ∈ [−52.5, 52.5], y ∈ [−34, 34].
- **Attacking frame:** each team reasons in its own frame, with its attack toward **+x**. The simulator stores absolute coordinates and converts per team.
- **Ball side:** when a play is instantiated, `side = sign(ball_y)` in the attacking frame. If |ball_y| < 2 m, pick the side with fewer opponents in the ball's band. Side is **frozen for the play's duration**. All play geometry is authored side-relative:
  - `dx` > 0 means toward the opponent goal.
  - `dy` > 0 means toward the **near (ball-side) touchline**.
  - This mirrors plays automatically, so each play only needs to be authored once.
- Simulation tick: 0.1 s.
- Distances are in meters, times in seconds, speeds in m/s.

### 3.1 Zones (attacking frame, side-relative lanes)

Let `ys = y * side`.

**Bands (by x):**

| band | x range |
|---|---|
| `own_third` | [−52.5, −17.5) |
| `mid_own` | [−17.5, 0) |
| `mid_opp` | [0, 17.5) |
| `final_third` | [17.5, 52.5] |

**Lanes (by ys).** Boundaries align with the box (half-width 20.16) and six-yard box (half-width 9.16):

| lane | ys range |
|---|---|
| `near_wing` | [20.16, 34] |
| `near_halfspace` | [9.16, 20.16) |
| `center` | [−9.16, 9.16) |
| `far_halfspace` | [−20.16, −9.16) |
| `far_wing` | [−34, −20.16) |

**Zone ids:** `band.lane` (e.g. `final_third.near_wing`). Wildcards are allowed: `mid_opp.*`, `*.center`.

**Special zones:**

| id | definition |
|---|---|
| `box` | x ≥ 36, \|y\| ≤ 20.16 |
| `own_box` | x ≤ −36, \|y\| ≤ 20.16 |
| `zone14` | 19 ≤ x < 36, \|ys\| ≤ 9.16 |
| `cutback_zone` | 41 ≤ x < 47, \|ys\| ≤ 9.16 |
| `near_post_area` | 47 ≤ x ≤ 52.5, 0 ≤ ys ≤ 9.16 |
| `far_post_area` | 44 ≤ x ≤ 52.5, −12 ≤ ys < −1 |
| `own_box_edge` | −36 < x ≤ −30, \|y\| ≤ 20.16 |

### 3.2 Dynamic lines

Cluster each team's outfield players by x (1-D k-means, k = 3, with fallback to fewer clusters when they collapse):

- `opp_first_line`, `opp_second_line`, `opp_last_line`
- `our_first_line`, `our_second_line`, `our_last_line`

"First" is the line nearest the opponent's attack. `opp_last_line` is the x of the deepest opponent outfielder, which is the offside line.

**Line height** is measured as the distance from the defending team's own goal line.

### 3.3 Anchors (named reference points)

- `ball`, `ball_holder`
- `goal` (opp goal center), `own_goal`, `near_post`, `far_post`, `penalty_spot`
- `byline_near` (x = 52.5, ys = ball_ys clipped to [9, 30])
- `role:<R>` (current position of the player bound to role R)
- `opp:<selector>` (see 3.5)
- `line:<name>` (x = line x, y = ball y)

Anchors are evaluated live each tick. Add `freeze: step_start` to snapshot one at step start.

### 3.4 Targets (where an action goes)

A target is one of the following. `resolve(target, state) -> point`, plus an optional receiver.

| form | meaning |
|---|---|
| `{role: R2, lead: 4}` | The player in R2. `lead` = meters ahead along their velocity (default 0). |
| `{anchor: X, offset: [dx, dy]}` | Anchor point plus side-relative offset. |
| `{zone: Z}` | Pitch-control-maximizing point for our team within Z. Add `pick: centroid` for the zone centroid. |
| `{pc_best: {zone: Z}, score: pc \| pc_xt}` | Point in the region maximizing pitch control, or PC × xT. Region can also be `{anchor: X, radius: r}`. |
| `{space_behind: {line: opp_last_line, lane: L, depth: d}}` | Point `d` m beyond the line, centered in lane L. |
| `{best_teammate: {score: xt \| pass_p \| pc_xt, zone: Z?}}` | Best receiver by score (optionally restricted to a zone). |
| `{opponent: <selector>}` | Defensive target (see 3.5). |

### 3.5 Opponent selectors

- `ball_carrier`
- `nearest_to_role:<R>`
- `nearest_to_ball`
- `nearest_receiver` (the opponent with the highest pass-reception probability from the carrier, excluding the carrier)
- `second_receiver`
- `in_zone:<Z>` (nearest opponent in zone Z)
- `most_dangerous` (highest xT at their position among those not already marked)

### 3.6 Side-relative position hints (for role assignment)

`GK, CB_near, CB_far, FB_near, FB_far, DM, CM, AM, W_near, W_far, ST`

The simulator maps each player's formation slot (e.g. LB, RCM) to a side-relative hint given the frozen side.

### 3.7 Player capabilities

All capabilities are floats in [0, 1]:

`pace, acceleration, stamina, passing, vision, crossing, dribbling, first_touch, finishing, aerial, tackling, positioning, composure`

---

## 4. Play schema (machine-executable)

Implement as pydantic models in `schema/`. Plays live in `plays/**/*.yaml`, one play per file.

### 4.1 Top level

```yaml
id: snake_case_unique          # required
name: Human-readable name
version: 1
phase: in_possession | out_of_possession | transition_attack | transition_defense | set_piece
objective: retain_possession | progress_ball | create_chance | score | regain_possession | delay | protect_goal
strategy: free-text tag         # e.g. wide_overload; becomes a node in Module 2's graph
fallback: false                 # true = always-available baseline play (no triggers needed besides phase)
roles: [Role, ...]
triggers: Predicate             # when the play is a candidate
hard_constraints: [Predicate]   # all must hold at instantiation (Module 2 hard gate)
steps: [Step, ...]
success: Predicate
abort: Predicate
max_duration_s: float
cooldown_s: float               # don't re-select the same play for N s after it ends
soft_hints: {risk: 0-1, chain_depth: int, tempo: slow|medium|fast}
source: library | generated | promoted   # set by loader/generator; library by default
```

### 4.2 Role

```yaml
- id: R1
  desc: text
  hints: [W_near, FB_near]       # side-relative position hints, ordered by preference
  requires: {dribbling: 0.4}     # HARD minimums (fail → player ineligible)
  prefers: {crossing: 1.0}       # SOFT weights (enter assignment cost)
  starts_with_ball: false
  group: null                    # or {count: 4} for unit roles (back line, midfield line)
```

- Group roles expand to `count` slots during assignment.
- Players not bound to any role follow the **shape controller** (Section 7.4).

### 4.3 Step

```yaml
- id: s1
  start_when: Predicate          # optional; default = previous step done (first step starts immediately)
  actions: [Action]              # OR `choose`, not both
  choose:                        # first option whose `when` holds is executed; `when: always` = else
    - when: Predicate
      actions: [Action]
  done_when: Predicate
  timeout_s: float
  on_timeout: abort | next | goto:<step_id>
  next: <step_id> | end          # default: next step in list
```

**Action persistence:** a role keeps executing its most recent action until a later step assigns it a new one or the action completes. After completion, a role holds its position facing the ball and does not drop to shape until the play ends.

### 4.4 Action

```yaml
{role: R1, type: <action_type>, ...params}
# or dynamic actor:
{actor: ball_holder, type: ...}
{actor: {nearest_to_ball_in: G_MID}, type: ...}   # nearest member of a group role
```

**Action vocabulary.** Every type must have a controller (Section 7.3).

| category | type | params |
|---|---|---|
| on-ball | `pass` | `to`, `style: ground\|driven\|lofted\|through`, `one_touch: bool` |
| on-ball | `cross` | `to`, `style: whipped\|lofted\|driven_low` |
| on-ball | `cutback` | `to` |
| on-ball | `carry` | `to`, `speed: jog\|fast\|max`, `protect: bool` |
| on-ball | `dribble` | `to`, `beat: <opp selector>` |
| on-ball | `shoot` | `placement: auto\|near\|far`, `style: placed\|power` |
| on-ball | `hold_up` | `duration_s` |
| on-ball | `clear` | `to` |
| on-ball | `distribute` (GK) | `to`, `style` |
| off-ball | `run_to` | `to`, `speed`, `arrive_with: <role>` (time arrival to the delivery) |
| off-ball | `overlap` / `underlap` | `around: <role>`, `to` |
| off-ball | `third_man_run` | `to` |
| off-ball | `spin_in_behind` | `line`, `lane`, `depth` |
| off-ball | `check_to_ball` | `distance`, `duration_s` |
| off-ball | `decoy_run` | `to` |
| off-ball | `support` | `from: <role>`, `angle: back_inside\|back_outside\|square\|forward`, `distance` |
| off-ball | `hold_width` | `lane` |
| off-ball | `hold_position` | `to` |
| defensive | `press` | `target`, `curve: force_outside\|force_inside\|none`, `intensity: 0-1` |
| defensive | `cover` | `behind: <role>`, `depth` |
| defensive | `mark` | `target`, `tightness` (m), `goal_side: bool` |
| defensive | `block_lane` | `from: <opp selector>`, `to: <opp selector>` |
| defensive | `block_shot` | — |
| defensive | `jockey` | `target` |
| defensive | `tackle` | `target` |
| defensive | `recover` | `to`, `speed` |
| defensive | `compact_shift` (group) | `line_height`, `width`, `ball_shift: 0-1` |
| defensive | `hold_line` (group) | `height`, `step_up_on: <event>` |
| keeper | `set_position` | `mode: cover_line\|sweep` |

### 4.5 Predicates

Predicates are **structured YAML, not strings**. The combinators are `all: [...]`, `any: [...]`, `not: P`, and literal `always`.

Comparisons use the keys `lt, le, gt, ge, eq`.

| predicate | form |
|---|---|
| possession | `possession: us\|them\|loose` |
| has_ball | `has_ball: R1 \| teammate \| opponent` |
| ball_in_zone | `ball_in_zone: Z` or a list (any-of) |
| role_in_zone | `role_in_zone: {role: R1, zone: Z}` |
| dist | `dist: {a: ref, b: ref, lt: 10}` (refs: `ball`, `ball_holder`, `role:R1`, `anchor:X`, `opp:<selector>`, `line:<name>`) |
| ahead_of | `ahead_of: {a: ref, b: ref, by: 3}` → x_a − x_b ≥ by |
| pressure_on | `pressure_on: {ref: role:R1, lt: 2}` → nearest opponent distance |
| lane_open | `lane_open: {from: R1, to: Target, min_p: 0.6}` → pass model success probability |
| pc_at | `pc_at: {target: Target, gt: 0.6}` |
| xg | `xg: {ref: ball_holder, gt: 0.08}` |
| line_height | `line_height: {line: opp_last_line, gt: 35}` |
| count_in_zone | `count_in_zone: {team: us\|them, zone: Z, le: 2}` |
| goal_side_count | `goal_side_count: {team: them, le: 5}` → outfielders between ball and their goal |
| teammates_near | `teammates_near: {ref: ball, radius: 15, ge: 3}` |
| onside | `onside: R2` |
| event | `event: <type>` or `event: {type: T, within_s: 1.5}` (default window: since current step started; at play level, since play start; in triggers, `within_s` is required) |
| ball_beyond_line | `ball_beyond_line: {line: L, by: 0}` → ball_x > line_x + by |
| ball_behind_line | `ball_behind_line: {line: L, by: 0}` → ball_x < line_x − by |
| elapsed | `elapsed_s: {gt: 10}` (play), `step_elapsed_s: {gt: 3}` |
| game | `game: {score_diff: {lt: 0}, minute: {gt: 80}}` |

**Event types:** `pass_completed, pass_intercepted, possession_won, possession_lost, shot_taken, goal, goal_conceded, ball_out, ball_out_them_last, foul_won, tackle_won, goal_kick_ours, goal_kick_theirs, corner_ours, throw_in_ours`

### 4.6 Validation rules (implement in the loader; fail loudly)

- Every referenced role, step id, zone id, anchor, selector, action type, and event type exists.
- Every action type's required params are present.
- Each step has exactly one of `actions` or `choose`.
- `starts_with_ball: true` appears on at most one role, and only in possession-phase plays.
- `goto` targets exist, and the step graph is acyclic unless a step has `timeout_s` (which prevents infinite loops).
- Generated plays (Module 3) pass the **same** validator. Anything that fails is discarded, never repaired silently.

If a starter play in Section 6 conflicts with this schema, fix the play to match the schema and record the change in `plays/CHANGELOG.md`.

---

## 5. Play executor (runtime)

`PlayInstance` = play definition + frozen `side` + role→player binding + step state machine.

1. **Instantiate:** freeze side, bind roles (from Module 2 assignment), resolve `freeze` anchors.
2. **Each tick:**
   - Check `abort`, then `success`, then `max_duration_s`.
   - Advance the current step: start when `start_when` holds; issue actions (or evaluate `choose` once at step start); check `done_when` and `timeout_s`.
   - Issue controller commands for every bound role.
3. **End reasons:** `success | abort | timeout | step_timeout_abort | preempted | possession_change`. Log the end reason.
4. Possession change ends every in-possession play (reason `possession_change`) unless the play's `phase` is a transition phase that expects it.

---

## 6. Starter play library (v1)

These 12 plays are the seed library. Numbers are initial guesses for tuning. They cover:
- **8 possession/attacking plays**, including an always-available fallback.
- **4 defensive plays**, needed so the opponent side of self-play is competent.

Put each play in `plays/offensive/<id>.yaml` or `plays/defensive/<id>.yaml`.

### 6.1 `wide_overlap_cross`

```yaml
id: wide_overlap_cross
name: Wide overlap and delivery
version: 1
phase: in_possession
objective: create_chance
strategy: wide_overload
roles:
  - id: R1
    desc: Wide player on the ball
    hints: [W_near, FB_near]
    requires: {dribbling: 0.4, passing: 0.4}
    starts_with_ball: true
  - id: R2
    desc: Overlapping full-back
    hints: [FB_near]
    requires: {pace: 0.5, stamina: 0.4}
    prefers: {crossing: 1.0, pace: 0.5}
  - id: R3
    desc: Striker attacking near post
    hints: [ST]
    prefers: {finishing: 1.0, aerial: 0.5}
  - id: R4
    desc: Far-side runner attacking far post
    hints: [W_far, AM]
    prefers: {finishing: 0.7, aerial: 0.7}
  - id: R5
    desc: Edge-of-box support for cutbacks and second balls
    hints: [AM, CM]
    prefers: {finishing: 0.5, passing: 0.5}
triggers:
  all:
    - possession: us
    - has_ball: R1
    - ball_in_zone: [mid_opp.near_wing, final_third.near_wing]
    - dist: {a: role:R2, b: role:R1, lt: 20}
    - count_in_zone: {team: them, zone: final_third.near_wing, le: 2}
hard_constraints:
  - not: {pressure_on: {ref: role:R1, lt: 1.5}}
steps:
  - id: s1
    actions:
      - {role: R1, type: carry, to: {anchor: ball, offset: [3, -5]}, speed: jog}
      - {role: R2, type: overlap, around: R1, to: {anchor: role:R1, offset: [12, 5]}}
      - {role: R3, type: run_to, to: {zone: final_third.center}, speed: fast}
      - {role: R4, type: run_to, to: {zone: final_third.far_halfspace}, speed: fast}
      - {role: R5, type: support, from: R1, angle: back_inside, distance: 12}
    done_when:
      all:
        - ahead_of: {a: role:R2, b: role:R1, by: 3}
        - lane_open: {from: R1, to: {role: R2, lead: 4}, min_p: 0.65}
    timeout_s: 5
    on_timeout: abort
  - id: s2
    actions:
      - {role: R1, type: pass, to: {role: R2, lead: 4}, style: ground}
    done_when: {has_ball: R2}
    timeout_s: 3
    on_timeout: abort
  - id: s3
    actions:
      - {role: R2, type: carry, to: {anchor: byline_near, offset: [-4, -3]}, speed: fast}
      - {role: R3, type: run_to, to: {zone: near_post_area}, speed: max, arrive_with: R2}
      - {role: R4, type: run_to, to: {zone: far_post_area}, speed: fast, arrive_with: R2}
      - {role: R5, type: run_to, to: {zone: cutback_zone}, speed: fast}
    done_when:
      any:
        - dist: {a: role:R2, b: anchor:byline_near, lt: 8}
        - pressure_on: {ref: role:R2, lt: 2}
    timeout_s: 4
    on_timeout: next
  - id: s4
    choose:
      - when: {pc_at: {target: {zone: cutback_zone}, gt: 0.6}}
        actions: [{role: R2, type: cutback, to: {role: R5}}]
      - when: {pc_at: {target: {zone: near_post_area}, gt: 0.5}}
        actions: [{role: R2, type: cross, to: {role: R3}, style: driven_low}]
      - when: always
        actions: [{role: R2, type: cross, to: {role: R4}, style: lofted}]
    done_when:
      any: [{event: pass_completed}, {event: pass_intercepted}, {event: ball_out}]
    timeout_s: 3
    on_timeout: abort
  - id: s5
    choose:
      - when: {xg: {ref: ball_holder, gt: 0.06}}
        actions: [{actor: ball_holder, type: shoot, placement: auto, style: placed}]
      - when: always
        actions: [{actor: ball_holder, type: pass, to: {best_teammate: {score: xt, zone: box}}, style: ground, one_touch: true}]
    done_when: {any: [{event: shot_taken}, {event: pass_completed}]}
    timeout_s: 2
    on_timeout: abort
success:
  any: [{event: shot_taken}, {event: goal}]
abort:
  any: [{event: possession_lost}, {event: ball_out}]
max_duration_s: 18
cooldown_s: 20
soft_hints: {risk: 0.4, chain_depth: 5, tempo: medium}
```

### 6.2 `third_man_combination`

```yaml
id: third_man_combination
name: Third-man combination through midfield
version: 1
phase: in_possession
objective: progress_ball
strategy: central_combination
roles:
  - id: R1
    desc: Deep passer on the ball
    hints: [CB_near, DM, CB_far]
    requires: {passing: 0.5}
    starts_with_ball: true
  - id: R2
    desc: Wall player checking to the ball
    hints: [CM, DM, AM]
    requires: {first_touch: 0.5, passing: 0.5}
    prefers: {composure: 0.8}
  - id: R3
    desc: Third man arriving between the lines
    hints: [AM, CM, W_near]
    requires: {first_touch: 0.4}
    prefers: {vision: 0.8, dribbling: 0.5}
  - id: R4
    desc: Striker pinning the last line
    hints: [ST]
    prefers: {pace: 0.6}
triggers:
  all:
    - possession: us
    - has_ball: R1
    - ball_in_zone: [own_third.center, own_third.near_halfspace, own_third.far_halfspace, mid_own.*, mid_opp.center, mid_opp.near_halfspace]
    - lane_open: {from: R1, to: {role: R2}, min_p: 0.75}
    - not: {lane_open: {from: R1, to: {role: R3}, min_p: 0.6}}
hard_constraints:
  - not: {pressure_on: {ref: role:R1, lt: 1.5}}
steps:
  - id: s1
    actions:
      - {role: R2, type: check_to_ball, distance: 6, duration_s: 1.0}
      - {role: R3, type: third_man_run, to: {pc_best: {zone: mid_opp.center}, score: pc_xt}}
      - {role: R4, type: hold_position, to: {anchor: line:opp_last_line, offset: [-1, 0]}}
    done_when: {step_elapsed_s: {gt: 0.8}}
    timeout_s: 1.5
    on_timeout: next
  - id: s2
    actions:
      - {role: R1, type: pass, to: {role: R2}, style: driven}
    done_when: {has_ball: R2}
    timeout_s: 2.5
    on_timeout: abort
  - id: s3
    choose:
      - when: {lane_open: {from: R2, to: {role: R3, lead: 2}, min_p: 0.6}}
        actions: [{role: R2, type: pass, to: {role: R3, lead: 2}, style: ground, one_touch: true}]
      - when: always
        actions: [{role: R2, type: pass, to: {role: R1}, style: ground, one_touch: true}]
    done_when: {any: [{has_ball: R3}, {has_ball: R1}]}
    timeout_s: 2.5
    on_timeout: abort
  - id: s4
    start_when: {has_ball: R3}
    choose:
      - when: {lane_open: {from: R3, to: {space_behind: {line: opp_last_line, lane: center, depth: 6}}, min_p: 0.45}}
        actions:
          - {role: R4, type: spin_in_behind, line: opp_last_line, lane: center, depth: 6}
          - {role: R3, type: pass, to: {space_behind: {line: opp_last_line, lane: center, depth: 6}}, style: through}
      - when: always
        actions: [{role: R3, type: carry, to: {zone: zone14}, speed: fast}]
    done_when: {any: [{event: pass_completed}, {ball_in_zone: zone14}, {event: possession_lost}]}
    timeout_s: 4
    on_timeout: abort
success:
  any:
    - all: [{has_ball: R3}, {ball_beyond_line: {line: opp_second_line}}]
    - ball_in_zone: zone14
    - all: [{possession: us}, {ball_beyond_line: {line: opp_last_line}}]
abort:
  any: [{event: possession_lost}, {all: [{has_ball: R1}, {step_elapsed_s: {gt: 1.0}}]}]
max_duration_s: 12
cooldown_s: 10
soft_hints: {risk: 0.35, chain_depth: 3, tempo: fast}
```

### 6.3 `switch_of_play`

```yaml
id: switch_of_play
name: Switch to the isolated far side
version: 1
phase: in_possession
objective: progress_ball
strategy: switch_overload
roles:
  - id: R1
    desc: Ball carrier on the crowded side
    hints: [FB_near, W_near, CM]
    starts_with_ball: true
  - id: R2
    desc: Pivot / switching passer
    hints: [DM, CB_near, CM]
    requires: {passing: 0.55}
    prefers: {vision: 1.0, passing: 0.8}
  - id: R3
    desc: Far-side wide receiver
    hints: [W_far, FB_far]
    requires: {first_touch: 0.4}
    prefers: {pace: 0.7, dribbling: 0.7}
  - id: R4
    desc: Far-side support
    hints: [FB_far, CM]
triggers:
  all:
    - possession: us
    - has_ball: R1
    - ball_in_zone: [mid_own.near_wing, mid_own.near_halfspace, mid_opp.near_wing, mid_opp.near_halfspace, final_third.near_wing]
    - count_in_zone: {team: them, zone: "*.far_wing", le: 1}
    - count_in_zone: {team: them, zone: "*.near_wing", ge: 3}
steps:
  - id: s1
    actions:
      - {role: R3, type: hold_width, lane: far_wing}
      - {role: R4, type: support, from: R3, angle: back_inside, distance: 12}
      - {role: R2, type: support, from: R1, angle: back_inside, distance: 14}
      - {role: R1, type: pass, to: {role: R2}, style: ground}
    done_when: {has_ball: R2}
    timeout_s: 3
    on_timeout: abort
  - id: s2
    choose:
      - when: {lane_open: {from: R2, to: {role: R3, lead: 3}, min_p: 0.6}}
        actions: [{role: R2, type: pass, to: {role: R3, lead: 3}, style: lofted}]
      - when: always
        actions: [{role: R2, type: pass, to: {role: R4}, style: driven}]
    done_when: {any: [{has_ball: R3}, {has_ball: R4}]}
    timeout_s: 3.5
    on_timeout: abort
  - id: s3
    start_when: {has_ball: R4}
    actions:
      - {role: R4, type: pass, to: {role: R3, lead: 3}, style: ground}
    done_when: {has_ball: R3}
    timeout_s: 3
    on_timeout: abort
  - id: s4
    actions:
      - {role: R3, type: carry, to: {pc_best: {zone: final_third.far_wing}, score: pc_xt}, speed: fast}
      - {role: R4, type: overlap, around: R3, to: {anchor: role:R3, offset: [10, -4]}}
    done_when: {any: [{ball_in_zone: "final_third.*"}, {pressure_on: {ref: role:R3, lt: 2}}]}
    timeout_s: 5
    on_timeout: next
success:
  all:
    - has_ball: R3
    - any: [{ball_in_zone: "final_third.*"}, {pressure_on: {ref: role:R3, gt: 5}}]
abort:
  any: [{event: possession_lost}, {event: ball_out}]
max_duration_s: 15
cooldown_s: 15
soft_hints: {risk: 0.3, chain_depth: 3, tempo: medium}
```

> Note: after the switch, R3 remains in the `far_*` lanes because side is frozen at instantiation.

### 6.4 `through_ball_behind_high_line`

```yaml
id: through_ball_behind_high_line
name: Through ball behind a high line
version: 1
phase: in_possession
objective: create_chance
strategy: exploit_depth
roles:
  - id: R1
    desc: Passer facing forward
    hints: [CM, AM, DM, CB_near]
    requires: {passing: 0.6, vision: 0.5}
    starts_with_ball: true
  - id: R2
    desc: Runner in behind
    hints: [ST, W_near, W_far]
    requires: {pace: 0.65}
    prefers: {finishing: 0.8, acceleration: 0.8}
  - id: R3
    desc: Second runner / decoy
    hints: [W_far, AM, ST]
    prefers: {pace: 0.5}
triggers:
  all:
    - possession: us
    - has_ball: R1
    - ball_in_zone: [mid_own.*, mid_opp.*]
    - line_height: {line: opp_last_line, gt: 35}
    - pressure_on: {ref: role:R1, gt: 3}
hard_constraints:
  - onside: R2
steps:
  - id: s1
    actions:
      - {role: R2, type: check_to_ball, distance: 3, duration_s: 0.8}
      - {role: R3, type: decoy_run, to: {anchor: line:opp_last_line, offset: [-2, -12]}}
      - {role: R1, type: carry, to: {anchor: ball, offset: [3, 0]}, speed: jog}
    done_when: {step_elapsed_s: {gt: 0.8}}
    timeout_s: 1.2
    on_timeout: next
  - id: s2
    actions:
      - {role: R2, type: spin_in_behind, line: opp_last_line, lane: center, depth: 10}
    done_when:
      all:
        - onside: R2
        - lane_open: {from: R1, to: {space_behind: {line: opp_last_line, lane: center, depth: 10}}, min_p: 0.4}
    timeout_s: 1.5
    on_timeout: abort
  - id: s3
    actions:
      - {role: R1, type: pass, to: {space_behind: {line: opp_last_line, lane: center, depth: 10}}, style: through}
    done_when: {any: [{has_ball: R2}, {event: pass_intercepted}, {event: ball_out}]}
    timeout_s: 3
    on_timeout: abort
  - id: s4
    choose:
      - when: {xg: {ref: role:R2, gt: 0.12}}
        actions: [{role: R2, type: shoot, placement: auto, style: placed}]
      - when: always
        actions:
          - {role: R2, type: carry, to: {anchor: penalty_spot, offset: [0, 0]}, speed: max}
          - {role: R3, type: run_to, to: {zone: far_post_area}, speed: max}
    done_when: {any: [{event: shot_taken}, {ball_in_zone: box}]}
    timeout_s: 4
    on_timeout: abort
success:
  any: [{event: shot_taken}, {all: [{has_ball: R2}, {ball_in_zone: box}]}]
abort:
  any: [{event: possession_lost}, {event: ball_out}]
max_duration_s: 12
cooldown_s: 15
soft_hints: {risk: 0.6, chain_depth: 2, tempo: fast}
```

### 6.5 `one_two_wall_pass`

```yaml
id: one_two_wall_pass
name: One-two to beat a single defender
version: 1
phase: in_possession
objective: create_chance
strategy: local_combination
roles:
  - id: R1
    desc: Carrier facing a defender
    hints: [AM, W_near, CM, ST]
    requires: {passing: 0.45}
    prefers: {pace: 0.6, finishing: 0.5}
    starts_with_ball: true
  - id: R2
    desc: Wall player
    hints: [ST, AM, CM, W_near]
    requires: {first_touch: 0.5}
triggers:
  all:
    - possession: us
    - has_ball: R1
    - ball_in_zone: [mid_opp.center, mid_opp.near_halfspace, final_third.near_halfspace, final_third.center, zone14]
    - dist: {a: role:R1, b: opp:nearest_to_role:R1, lt: 6}
    - dist: {a: role:R1, b: role:R2, lt: 14}
    - lane_open: {from: R1, to: {role: R2}, min_p: 0.7}
steps:
  - id: s1
    actions:
      - {role: R1, type: pass, to: {role: R2}, style: ground}
    done_when: {event: pass_completed}
    timeout_s: 2
    on_timeout: abort
  - id: s2
    actions:
      - {role: R1, type: run_to, to: {anchor: "opp:nearest_to_role:R1", offset: [7, 0], freeze: step_start}, speed: max}
    done_when:
      lane_open: {from: R2, to: {role: R1, lead: 3}, min_p: 0.6}
    timeout_s: 1.5
    on_timeout: abort
  - id: s3
    actions:
      - {role: R2, type: pass, to: {role: R1, lead: 3}, style: ground, one_touch: true}
    done_when: {has_ball: R1}
    timeout_s: 2
    on_timeout: abort
  - id: s4
    choose:
      - when: {xg: {ref: role:R1, gt: 0.08}}
        actions: [{role: R1, type: shoot, placement: auto, style: placed}]
      - when: always
        actions: [{role: R1, type: carry, to: {pc_best: {zone: box}, score: pc_xt}, speed: fast}]
    done_when: {any: [{event: shot_taken}, {ball_in_zone: box}]}
    timeout_s: 3
    on_timeout: abort
success:
  any: [{event: shot_taken}, {all: [{has_ball: R1}, {ball_in_zone: box}]}]
abort:
  any: [{event: possession_lost}]
max_duration_s: 9
cooldown_s: 8
soft_hints: {risk: 0.35, chain_depth: 2, tempo: fast}
```

### 6.6 `build_out_short_goal_kick`

```yaml
id: build_out_short_goal_kick
name: Short build-out from goal kick
version: 1
phase: set_piece
objective: progress_ball
strategy: build_from_back
roles:
  - id: GK
    hints: [GK]
    starts_with_ball: true
  - id: C1
    desc: Near-side center-back splitting wide
    hints: [CB_near]
    requires: {first_touch: 0.4}
  - id: C2
    desc: Far-side center-back splitting wide
    hints: [CB_far]
  - id: D1
    desc: Pivot dropping between CBs
    hints: [DM, CM]
    requires: {first_touch: 0.5, passing: 0.5}
    prefers: {composure: 1.0}
  - id: F1
    desc: Near full-back high and wide
    hints: [FB_near]
  - id: F2
    desc: Far full-back high and wide
    hints: [FB_far]
  - id: S1
    desc: Long-ball outlet
    hints: [ST]
    prefers: {aerial: 1.0}
triggers:
  all:
    - event: {type: goal_kick_ours, within_s: 1.0}
steps:
  - id: s1
    actions:
      - {role: C1, type: run_to, to: {anchor: own_goal, offset: [14, 18]}, speed: jog}
      - {role: C2, type: run_to, to: {anchor: own_goal, offset: [14, -18]}, speed: jog}
      - {role: D1, type: run_to, to: {anchor: own_goal, offset: [22, 0]}, speed: jog}
      - {role: F1, type: hold_width, lane: near_wing}
      - {role: F2, type: hold_width, lane: far_wing}
      - {role: S1, type: hold_position, to: {zone: mid_opp.center, pick: centroid}}
    done_when: {step_elapsed_s: {gt: 3}}
    timeout_s: 4
    on_timeout: next
  - id: s2
    choose:
      - when: {lane_open: {from: GK, to: {role: C1}, min_p: 0.85}}
        actions: [{role: GK, type: distribute, to: {role: C1}, style: ground}]
      - when: {lane_open: {from: GK, to: {role: C2}, min_p: 0.85}}
        actions: [{role: GK, type: distribute, to: {role: C2}, style: ground}]
      - when: {lane_open: {from: GK, to: {role: D1}, min_p: 0.8}}
        actions: [{role: GK, type: distribute, to: {role: D1}, style: ground}]
      - when: always
        actions: [{role: GK, type: distribute, to: {role: S1}, style: lofted}]
    done_when: {any: [{event: pass_completed}, {event: pass_intercepted}, {event: ball_out}]}
    timeout_s: 4
    on_timeout: abort
  - id: s3
    choose:
      - when: {has_ball: S1}
        actions: [{role: S1, type: hold_up, duration_s: 1.5}]
      - when: {lane_open: {from: ball_holder, to: {role: F1}, min_p: 0.7}}
        actions: [{actor: ball_holder, type: pass, to: {role: F1}, style: ground}]
      - when: {lane_open: {from: ball_holder, to: {role: D1}, min_p: 0.7}}
        actions: [{actor: ball_holder, type: pass, to: {role: D1}, style: ground}]
      - when: always
        actions: [{actor: ball_holder, type: carry, to: {anchor: ball, offset: [8, 0]}, speed: jog, protect: true}]
    done_when: {any: [{event: pass_completed}, {ball_beyond_line: {line: opp_first_line}}]}
    timeout_s: 5
    on_timeout: abort
success:
  all: [{possession: us}, {ball_beyond_line: {line: opp_first_line}}]
abort:
  any: [{event: possession_lost}, {event: ball_out}]
max_duration_s: 16
cooldown_s: 0
soft_hints: {risk: 0.35, chain_depth: 3, tempo: slow}
```

> Note: `lane_open.from` accepts a role id or `ball_holder`.

### 6.7 `direct_counterattack`

```yaml
id: direct_counterattack
name: Direct counterattack after regain
version: 1
phase: transition_attack
objective: create_chance
strategy: counter
roles:
  - id: R1
    desc: Ball winner / first passer
    hints: [DM, CM, CB_near, FB_near]
    starts_with_ball: true
  - id: R2
    desc: Fastest forward, runs in behind
    hints: [ST, W_near, W_far]
    requires: {pace: 0.6}
    prefers: {pace: 1.0, finishing: 0.6}
  - id: R3
    desc: Second runner (opposite channel)
    hints: [W_far, W_near, AM]
    requires: {pace: 0.5}
  - id: R4
    desc: Trailing support
    hints: [AM, CM]
triggers:
  all:
    - event: {type: possession_won, within_s: 1.5}
    - has_ball: R1
    - ball_in_zone: [own_third.*, mid_own.*, mid_opp.*]
    - goal_side_count: {team: them, le: 5}
steps:
  - id: s1
    actions:
      - {role: R2, type: spin_in_behind, line: opp_last_line, lane: center, depth: 8}
      - {role: R3, type: run_to, to: {anchor: ball, offset: [25, -18]}, speed: max}
      - {role: R4, type: run_to, to: {anchor: ball, offset: [12, 0]}, speed: fast}
    done_when: {step_elapsed_s: {gt: 0.3}}
    timeout_s: 0.5
    on_timeout: next
  - id: s1b
    choose:
      - when: {lane_open: {from: R1, to: {space_behind: {line: opp_last_line, lane: center, depth: 8}}, min_p: 0.45}}
        actions: [{role: R1, type: pass, to: {space_behind: {line: opp_last_line, lane: center, depth: 8}}, style: through}]
      - when: {lane_open: {from: R1, to: {role: R4}, min_p: 0.75}}
        actions: [{role: R1, type: pass, to: {role: R4}, style: driven}]
      - when: always
        actions: [{role: R1, type: carry, to: {anchor: ball, offset: [10, 0]}, speed: fast}]
    done_when: {any: [{event: pass_completed}, {step_elapsed_s: {gt: 2}}]}
    timeout_s: 3
    on_timeout: abort
  - id: s2
    choose:
      - when: {has_ball: R4}
        actions: [{role: R4, type: pass, to: {best_teammate: {score: pc_xt}}, style: through}]
      - when: always
        actions: [{actor: ball_holder, type: carry, to: {anchor: penalty_spot, offset: [0, 0]}, speed: max}]
    done_when: {any: [{ball_in_zone: box}, {event: pass_completed}, {pressure_on: {ref: ball_holder, lt: 2}}]}
    timeout_s: 5
    on_timeout: next
  - id: s3
    choose:
      - when: {xg: {ref: ball_holder, gt: 0.08}}
        actions: [{actor: ball_holder, type: shoot, placement: auto, style: placed}]
      - when: always
        actions: [{actor: ball_holder, type: pass, to: {best_teammate: {score: xt, zone: box}}, style: ground}]
    done_when: {any: [{event: shot_taken}, {event: pass_completed}]}
    timeout_s: 3
    on_timeout: abort
success:
  any: [{event: shot_taken}, {all: [{possession: us}, {ball_in_zone: box}]}]
abort:
  any: [{event: possession_lost}, {goal_side_count: {team: them, ge: 7}}]
max_duration_s: 14
cooldown_s: 0
soft_hints: {risk: 0.5, chain_depth: 3, tempo: fast}
```

### 6.8 `recycle_possession` (fallback)

```yaml
id: recycle_possession
name: Recycle to the safest option
version: 1
phase: in_possession
objective: retain_possession
strategy: circulation
fallback: true
roles:
  - id: R1
    desc: Ball carrier
    hints: [CB_near, CB_far, DM, CM, FB_near, FB_far, AM, W_near, W_far, ST, GK]
    starts_with_ball: true
triggers:
  all:
    - possession: us
    - has_ball: R1
steps:
  - id: s1
    choose:
      - when: {pressure_on: {ref: role:R1, gt: 4}}
        actions: [{role: R1, type: carry, to: {pc_best: {anchor: ball, radius: 8}, score: pc}, speed: jog, protect: true}]
      - when: always
        actions: [{role: R1, type: pass, to: {best_teammate: {score: pass_p}}, style: ground}]
    done_when: {any: [{event: pass_completed}, {step_elapsed_s: {gt: 2}}]}
    timeout_s: 3
    on_timeout: abort
success:
  any: [{event: pass_completed}, {all: [{possession: us}, {elapsed_s: {gt: 2}}]}]
abort:
  any: [{event: possession_lost}]
max_duration_s: 4
cooldown_s: 0
soft_hints: {risk: 0.1, chain_depth: 1, tempo: slow}
```

> The fallback guarantees Module 2 always has at least one in-possession candidate. It also gives the critic a baseline to compare against.

### 6.9 `high_press_sideline_trap`

```yaml
id: high_press_sideline_trap
name: Sideline pressing trap
version: 1
phase: out_of_possession
objective: regain_possession
strategy: high_press
roles:
  - id: P1
    desc: First presser, curves run to force play wide
    hints: [ST, W_near, AM]
    requires: {stamina: 0.5}
    prefers: {pace: 0.8, acceleration: 0.8}
  - id: P2
    desc: Cover-shadow presser blocking the inside lane
    hints: [AM, CM, ST]
    requires: {stamina: 0.5}
  - id: M1
    desc: Midfielder marking nearest central receiver
    hints: [CM, DM]
    prefers: {tackling: 0.6, positioning: 0.6}
  - id: F1
    desc: Full-back jumping onto the wide receiver
    hints: [FB_near]
    requires: {pace: 0.5}
    prefers: {tackling: 0.8}
  - id: B
    desc: Back line stepping up
    hints: [CB_near, CB_far, FB_far]
    group: {count: 3}
triggers:
  all:
    - possession: them
    - ball_in_zone: [final_third.near_wing, final_third.near_halfspace, mid_opp.near_wing]
    - teammates_near: {ref: ball, radius: 20, ge: 3}
hard_constraints:
  - game: {minute: {lt: 88}}
steps:
  - id: s1
    actions:
      - {role: P1, type: press, target: {opponent: ball_carrier}, curve: force_outside, intensity: 1.0}
      - {role: P2, type: block_lane, from: ball_carrier, to: nearest_receiver}
      - {role: M1, type: mark, target: {opponent: "in_zone:mid_opp.center"}, tightness: 2, goal_side: true}
      - {role: F1, type: mark, target: {opponent: "in_zone:mid_opp.near_wing"}, tightness: 1.5, goal_side: true}
      - {role: B, type: compact_shift, line_height: 50, width: 40, ball_shift: 0.7}
    done_when:
      any:
        - event: possession_won
        - event: ball_out_them_last
        - ball_behind_line: {line: our_second_line}
    timeout_s: 8
    on_timeout: abort
success:
  any: [{event: possession_won}, {event: ball_out_them_last}]
abort:
  any:
    - ball_behind_line: {line: our_second_line, by: 5}
    - event: goal_conceded
max_duration_s: 10
cooldown_s: 6
soft_hints: {risk: 0.6, chain_depth: 1, tempo: fast}
```

> Line heights for our defensive groups are measured from **our own goal line** (e.g. 50 = 50 m from our goal ≈ just past halfway). This matches 3.2.

### 6.10 `mid_block_compact`

```yaml
id: mid_block_compact
name: Compact mid-block
version: 1
phase: out_of_possession
objective: regain_possession
strategy: mid_block
roles:
  - id: G_FWD
    hints: [ST, AM]
    group: {count: 2}
  - id: G_MID
    hints: [W_near, CM, DM, W_far]
    group: {count: 4}
  - id: G_BACK
    hints: [FB_near, CB_near, CB_far, FB_far]
    group: {count: 4}
triggers:
  all:
    - possession: them
    - ball_in_zone: [mid_own.*, mid_opp.*]
steps:
  - id: s1
    actions:
      - {role: G_FWD, type: compact_shift, line_height: 55, width: 20, ball_shift: 0.5}
      - {role: G_MID, type: compact_shift, line_height: 42, width: 38, ball_shift: 0.7}
      - {role: G_BACK, type: compact_shift, line_height: 30, width: 42, ball_shift: 0.6}
    done_when: always
    timeout_s: 0.1
    on_timeout: next
  - id: s2
    choose:
      - when:
          all:
            - ball_in_zone: [mid_own.*, mid_opp.near_wing, mid_opp.near_halfspace]
            - pressure_on: {ref: opp:ball_carrier, gt: 3}
        actions:
          - {actor: {nearest_to_ball_in: G_MID}, type: press, target: {opponent: ball_carrier}, curve: force_outside, intensity: 0.8}
      - when: always
        actions:
          - {actor: {nearest_to_ball_in: G_MID}, type: jockey, target: {opponent: ball_carrier}}
    done_when:
      any: [{event: possession_won}, {event: ball_out_them_last}, {ball_in_zone: "own_third.*"}]
    timeout_s: 15
    on_timeout: next
success:
  any: [{event: possession_won}, {event: ball_out_them_last}]
abort:
  any: [{ball_in_zone: "own_third.*"}, {event: goal_conceded}]
max_duration_s: 15
cooldown_s: 0
soft_hints: {risk: 0.25, chain_depth: 1, tempo: medium}
```

### 6.11 `low_block_box_protection`

```yaml
id: low_block_box_protection
name: Low block protecting the box
version: 1
phase: out_of_possession
objective: protect_goal
strategy: low_block
roles:
  - id: G_BACK
    hints: [FB_near, CB_near, CB_far, FB_far]
    group: {count: 4}
  - id: G_MID
    hints: [W_near, CM, DM, W_far]
    group: {count: 4}
  - id: F1
    desc: Forward staying high as counter outlet
    hints: [ST]
    prefers: {pace: 0.8}
  - id: F2
    desc: Forward dropping to screen the pivot
    hints: [AM, ST]
  - id: GK
    hints: [GK]
triggers:
  all:
    - possession: them
    - ball_in_zone: ["own_third.*", own_box_edge]
steps:
  - id: s1
    actions:
      - {role: G_BACK, type: compact_shift, line_height: 12, width: 36, ball_shift: 0.5}
      - {role: G_MID, type: compact_shift, line_height: 22, width: 34, ball_shift: 0.7}
      - {role: F2, type: block_lane, from: ball_carrier, to: "in_zone:zone14"}
      - {role: F1, type: hold_position, to: {anchor: own_goal, offset: [50, 0]}}
      - {role: GK, type: set_position, mode: cover_line}
    done_when: always
    timeout_s: 0.1
    on_timeout: next
  - id: s2
    choose:
      - when: {ball_in_zone: [own_box, own_box_edge]}
        actions:
          - {actor: {nearest_to_ball_in: G_BACK}, type: press, target: {opponent: ball_carrier}, curve: force_outside, intensity: 1.0}
          - {actor: {nearest_to_ball_in: G_MID}, type: block_shot}
      - when: always
        actions:
          - {actor: {nearest_to_ball_in: G_MID}, type: jockey, target: {opponent: ball_carrier}}
    done_when:
      any: [{event: possession_won}, {event: ball_out_them_last}, {ball_in_zone: "mid_own.*"}]
    timeout_s: 20
    on_timeout: next
success:
  any: [{event: possession_won}, {event: ball_out_them_last}, {ball_in_zone: "mid_own.*"}]
abort:
  any: [{event: goal_conceded}]
max_duration_s: 20
cooldown_s: 0
soft_hints: {risk: 0.15, chain_depth: 1, tempo: slow}
```

### 6.12 `counterpress_five_seconds`

```yaml
id: counterpress_five_seconds
name: Immediate counterpress after loss
version: 1
phase: transition_defense
objective: regain_possession
strategy: counterpress
roles:
  - id: P1
    desc: Nearest player presses carrier
    hints: [AM, CM, W_near, ST, W_far]
    requires: {stamina: 0.4}
  - id: P2
    desc: Blocks nearest receiver
    hints: [CM, AM, W_near]
  - id: P3
    desc: Blocks second receiver
    hints: [DM, CM, W_far]
  - id: REST
    desc: Rest defense holds line
    hints: [CB_near, CB_far, FB_far]
    group: {count: 3}
triggers:
  all:
    - event: {type: possession_lost, within_s: 1.0}
    - ball_in_zone: ["mid_opp.*", "final_third.*"]
    - teammates_near: {ref: ball, radius: 15, ge: 3}
hard_constraints:
  - game: {minute: {lt: 88}}
steps:
  - id: s1
    actions:
      - {role: P1, type: press, target: {opponent: ball_carrier}, curve: none, intensity: 1.0}
      - {role: P2, type: block_lane, from: ball_carrier, to: nearest_receiver}
      - {role: P3, type: block_lane, from: ball_carrier, to: second_receiver}
      - {role: REST, type: hold_line, height: 45, step_up_on: possession_won}
    done_when: {any: [{event: possession_won}, {event: ball_out_them_last}]}
    timeout_s: 5
    on_timeout: abort
success:
  any: [{event: possession_won}, {event: ball_out_them_last}]
abort:
  any: [{ball_behind_line: {line: our_second_line}}, {elapsed_s: {gt: 5}}]
max_duration_s: 5
cooldown_s: 0
soft_hints: {risk: 0.5, chain_depth: 1, tempo: fast}
```

### 6.13 Library tests (required)

- **Validator tests.** All 12 files load and validate. Also create hand-written invalid fixtures in `tests/fixtures/invalid_plays/` that must **fail** with clear errors. Include at least:
  - a step with both `actions` and `choose`,
  - `done_when: {always: true}` (the literal must be `always`),
  - an undefined role reference,
  - an unknown zone id,
  - a `goto` to a missing step,
  - two roles with `starts_with_ball: true`.
- **Execution tests.** For each play, build a hand-crafted scenario where its triggers hold. The play must instantiate, run to an end reason without exceptions, and emit a well-formed log record.
- **Mirror test.** Each possession play, instantiated with the ball on the left and on the right, produces mirror-image target coordinates (tolerance 0.5 m).

---

## 7. Simulator (play-level, 2D)

A custom lightweight 2D simulator. Players are point masses; the ball is a point with 2D ground motion plus a flight model for lofted passes. Plays are high-level "options" executed by low-level controllers.

### 7.1 State

- **Players:** position, velocity, heading, team, formation slot, capabilities, stamina (current), and a `has_ball` flag.
- **Ball:** position, velocity, height state (`ground | air`), time-to-land, last touch team.
- **Match:** clock, score, possession, restart state, and an event queue.

### 7.2 Physics and resolution models (all configurable in `configs/sim.yaml`)

**Movement:**
- max speed = 7.0 + 2.5 × pace (m/s)
- accel = 3.0 + 2.0 × acceleration (m/s²)
- max speed is scaled by `0.85 + 0.15 × stamina_current`
- stamina drains with sprinting and recovers slowly

**Ball:**
- ground passes decelerate at ~2.5 m/s² (friction)
- lofted passes follow a ballistic flight time to target and are uncontested in flight, then contested on landing

**Pass success:**
- For each opponent, compute time-to-intercept along the ball path vs. ball arrival time, using the Spearman-style reaction time of 0.7 s.
- Interception probability is a logistic function of the time margin.
- Execution noise: angular error σ = base × (1 − passing) and speed error, both scaled by pressure on the passer.
- `lane_open` uses the **same** model (without noise sampling) to return a probability.

**First touch / control:** control probability depends on first_touch, ball speed, and pressure. Failure produces a loose ball.

**Dribble / tackle:**
- Contested duel probability = f(dribbling vs tackling, relative approach angle).
- A foul probability applies on failed tackles.

**Shots:**
- xG model = f(distance, angle, pressure, body/air).
- Outcome sampled with xG × `(0.7 + 0.6 × finishing)`, clipped.
- The GK save model reduces this based on GK position.

**Restarts:** throw-ins, goal kicks, corners, and kickoffs. Spawn simple restart setups. Set-piece plays can override them.

**Offside:** standard offside, evaluated at pass release.

### 7.3 Controllers

One controller per action type (4.4). A controller converts an action plus live state into a steering target (position/velocity) and ball commands. Controllers must:

- respect player speed and acceleration limits,
- implement timing (`arrive_with` = scale run speed to arrive when the ball is expected at the target),
- report completion (e.g. a run completes within 1 m of the target; a pass completes on release).

### 7.4 Shape controller (default behavior)

Unassigned players hold formation slots relative to the ball. Each slot's target = formation base position, shifted toward ball x/y by team-level compactness parameters, with separate in/out-of-possession shapes. Formation is config (start with 4-3-3; add 4-4-2 and 3-5-2).

### 7.5 Decision cadence and preemption

Each team has at most one **active play**. Out of possession, the active play is a defensive play.

Module 2 re-ranks when:
- the active play ends,
- possession changes,
- a restart occurs, or
- every **2.0 s** as an interrupt check.

On an interrupt, a new play preempts the active one only if `score_new − score_active > preempt_margin` (hysteresis, default 0.02 EPV units). The preempted play ends with reason `preempted`.

### 7.6 Environment interface

```python
class MatchEnv:
    def reset(self, seed: int, scenario: Scenario) -> MatchState: ...
    def run(self, home: Policy, away: Policy, max_time_s: float) -> EpisodeResult: ...

class Policy(Protocol):
    def decide(self, obs: TeamObservation, reason: DecisionReason) -> PlayInstance | None: ...
```

The env ticks internally and calls `decide` at decision points only.

`TeamObservation` = the Module 1 dashboard for that team, in the team's attacking frame.

### 7.7 Scenarios

Train on **short scenario episodes** (20–60 s) sampled from start-state distributions, not full 90-minute matches. The scenario types are:

- `build_up` (goal kick / CB on ball)
- `mid_progression`
- `final_third_attack`
- `transition_win` / `transition_loss`
- `set_piece_corner` (stub for now)
- `random_open_play`

An episode ends at a goal, a possession change + 8 s, or the time limit. A full-match mode is used for evaluation only.

---

## 8. Module 1 — Information Dashboard

`dashboard/` computes, per team per decision point (and cached per tick where needed):

1. **Team state:** positions, velocities, capabilities, stamina, formation slots, side-relative hints.
2. **Opponent model:**
   - v1: running statistics of the opponent's chosen plays per phase/zone, plus their average line heights and press intensity.
   - v2 (M7): output of the learned response model.
3. **Game state:** clock, score, possession, restart state, recent events.
4. **Geometry layer:**
   - **Pitch control:** Spearman (2018)-style time-to-intercept model on a 2 m grid (53 × 34), vectorized.
   - **xT surface:** 16 × 12 grid. Start with a distance/angle-based placeholder surface in config. Replace it with a value-iterated xT from sim event data (M6) and later SoccerNet (M10).
   - **EPV proxy:** `EPV(state) = PC-weighted xT at ball location + possession term`. This is the currency of rewards and scores.
   - **Pass-lane probabilities** for ball holder → each teammate (same model as 7.2).
   - **Lines** (3.2) and zone occupancy counts.
5. **Predicate evaluator:** implements every predicate in 4.5 against the dashboard. Unit-test each predicate.

---

## 9. Module 2 — Play Ranking

For a team at a decision point:

1. **Candidate set:**
   - Library plays whose `phase` matches and whose `triggers` hold (with the play's `R1`/`starts_with_ball` role provisionally bound to the ball holder).
   - Plus fallback plays.
   - Plus generated plays (from Module 3, when enabled).
   - Minus plays in cooldown.
2. **Hard gate:** evaluate `hard_constraints`, roster availability, and capability `requires` minimums. Remove failures.
3. **Role assignment** (per candidate):
   - Build a cost matrix of players × role slots. Group roles expand to `count` slots.
   - `cost = w_hint × hint_rank_cost + w_pref × (1 − prefers-weighted capability) + w_dist × travel_time_to_role_start + w_fatigue × (1 − stamina)`.
   - Ineligible pairs get cost `1e6`.
   - Solve with `linear_sum_assignment`. Any `1e6` in the solution means the play is infeasible, so drop it.
4. **Score** (all terms in **EPV units**, per the design doc's unified-ranking rule):
   ```
   score = graph_path_value(objective, strategy | game_state)
         − Σ soft_penalties(risk, fatigue, tactical_fit, chain_depth, execution_confidence)
         − λ_assign × normalized_assignment_cost
         + critic_value(state, play)          # 0 until M7
   ```
   - `graph_path_value` comes from the objective → strategy → play weighted graph. Weights are in `configs/ranking.yaml` and depend on game state (e.g. trailing late raises `create_chance`).
   - `chain_depth` penalty = `κ × chain_depth` (default κ = 0.005).
5. **Select** the argmax. During self-play, use softmax sampling with temperature τ for exploration (config; τ = 0 at eval). Log **all** candidates with score components.

---

## 10. Module 3 — Generator, critic, response model

### 10.1 State encoder (GNN)

- **Nodes:** 22 players + ball.
- **Node features:** position and velocity (attacking frame, side-normalized), team flag, side-relative hint one-hot, capabilities, stamina, local pitch control, xT at position, `has_ball`.
- **Edges:** fully connected, with distance, relative velocity, and same-team flag.
- **Model:** 3–4 layers of GATv2 or message-passing. Output node embeddings plus a pooled graph embedding.

### 10.2 Play tokenizer

Serialize a play to a token sequence under a **grammar**:

```
PHASE OBJ [ROLE hint* req_bins*]+ [STEP [ACTION role type target_tokens param_bins]+ DONE_pred TIMEOUT_bin]+ SUCCESS_pred ABORT_pred END
```

- Targets and offsets are discretized: offsets on a 2 m grid within [−30, 30]; zones and anchors are categorical.
- Predicates use a restricted, tokenizable subset.
- **Implement grammar-constrained decoding:** at each step, mask the logits to tokens that keep the sequence schema-valid. Every decoded sequence must detokenize to YAML that passes the 4.6 validator. Track the validity rate as a metric; the target is > 99%.

### 10.3 Generator

- Transformer decoder (6 layers, d = 256) conditioned on the GNN graph embedding plus the ball-holder node embedding (cross-attention).
- Keep the interface generic (`Generator.sample(obs, n) -> list[Play]`) so a diffusion variant can be swapped in later.
- Generated plays get `source: generated` and a unique id (hash of the tokens).

### 10.4 Critic

`Q(state, play) -> {epv_delta_mean, success_prob}`.

- **Input:** graph embedding plus play embedding (a transformer encoder over play tokens).
- **Training target:** realized EPV delta over the play horizon, plus the end-reason label.
- Its output enters Module 2's score in EPV units.

### 10.5 Response model

`R(state, play) -> distribution over opponent's next play id / archetype + distribution over outcome events within horizon`.

It is used for:
- the Module 1 opponent model v2,
- optional one-step lookahead in ranking: `score += γ × E[critic after opponent response]`, behind a flag.

---

## 11. Self-play training pipeline

### Phase A — Library self-play (data only, no learning in the policy)

- Both teams run Modules 1 and 2 with library plays only, with exploration temperature τ > 0.
- Vary formations, capability profiles (randomized per episode), and scenarios.
- Generate at least 200k decision records.
- Train the **critic** and **response model** offline.
- Recompute **xT** from sim events.

### Phase B — Generator pretraining (imitation + filtered mutation)

1. **Behavior cloning:** for each logged decision where a library play was chosen, train the generator to emit that play (tokenized, with side normalized) given the state.
2. **Mutation augmentation.** Mutate library plays with the following operators:
   - perturb offsets (±2–6 m),
   - swap an action for another in the same category,
   - change target types,
   - insert or delete a step,
   - change pass styles,
   - re-bind roles to different hints.
   
   Validate each mutant, run it in matching scenarios (≥ 20 rollouts each), and keep the top quantile by EPV delta. Add the survivors to the BC dataset (filtered self-imitation).
3. **Target:** at least 99% validity, and generated plays reach ≥ 80% of the library's mean EPV delta in matched scenarios.

### Phase C — RL fine-tuning in a league

1. Enable generated plays in Module 2: sample `k = 4` per decision, critic-scored, competing with library plays.
2. **Policy gradient on the generator:**
   - PPO over the token sequence, with reward = realized play-level EPV delta (plus terminal goal ±1).
   - Advantage = reward − critic baseline.
   - KL penalty to the Phase B generator (β configurable) to prevent drift into sim exploits and gibberish.
3. **League** (AlphaStar-style):
   - **Main agent:** plays both sides with shared weights.
   - **Snapshots:** frozen copy every N updates, added to the pool.
   - **Main exploiter:** trained only against the current main agent, then reset periodically.
   - **League exploiter:** trained against the whole pool.
   - **Scripted style opponents** (library-only, fixed play weights):
     - `high_press`: favors 6.9 and 6.12
     - `mid_block`: favors 6.10
     - `low_block_counter`: favors 6.11 and 6.7
     - `possession`: favors 6.2, 6.3, 6.8
   - **Opponent sampling:** prioritized fictitious self-play (PFSP), weighted toward opponents the main agent struggles against.
   - Track a payoff matrix and Elo.
4. **Continual critic/response-model training** on the growing dataset.

### Quality-diversity archive (runs during Phase C)

- MAP-Elites archive of generated plays.
- **Descriptors:** start band × start lane × tempo × number of passes × objective.
- Each cell keeps the best play by mean EPV delta, with a minimum of 50 evaluations.
- **Promotion pipeline:** archive elites that beat the library median in their niche across all scripted opponents are exported to `plays/promoted/<id>.yaml` with provenance (metrics, generating checkpoint). They are **flagged for human review** before joining the library.

### Anti-exploit measures

- Domain randomization: capabilities, reaction time (0.6–0.8 s), noise scales, friction.
- Every 20 updates, evaluate on a **held-out** sim config (different noise and physics parameters). If performance drops significantly relative to the training config, flag it as possible overfitting to sim quirks.
- Hold out one scripted style opponent (`possession`) from training entirely for evaluation.

---

## 12. Rewards

Per play (from instantiation to end):

```
r = ΔEPV(end − start)
  + 1.0 × goal_scored − 1.0 × goal_conceded
  − c_loss × possession_lost_in_own_half        # small, default 0.01
```

- Out-of-possession plays: `r = −ΔEPV_opponent` + regain bonus (default 0.02).
- Discount across consecutive plays within an episode: γ = 0.97 per play.
- **Guard against possession farming:** cap the reward from consecutive `retain_possession` plays that don't increase EPV.

---

## 13. Logging and data

Parquet, partitioned by run/date. One row per decision:

| field | content |
|---|---|
| `episode_id, t, team, reason` | decision context |
| `state` | compact serialized dashboard (positions, velocities, capabilities, PC summary stats, lines) |
| `candidates` | list of {play_id, source, feasible, score_components} |
| `chosen` | play_id, source, tokens (if generated), role binding |
| `opp_active_play` | opponent's play id at decision time and at play end |
| `events` | events during the play |
| `end_reason, duration_s` | |
| `epv_start, epv_end, reward` | |
| `sim_config_hash, policy_checkpoint, opponent_id` | provenance |

Also store full 10 Hz tracking per episode (separate files) for the **replay viewer**. The viewer draws the pitch, players, ball, the active play's name per team, role labels, and targets, and exports an MP4/GIF or static HTML.

---

## 14. Milestones (build in order; each has acceptance criteria)

| # | Milestone | Acceptance |
|---|---|---|
| M0 | Repo scaffold, config system, pydantic schema, loader, validator | All 12 starter plays validate. All invalid fixtures (6.13) fail with clear errors. CI runs pytest + ruff. |
| M1 | Simulator core: movement, ball, pass/interception, control, duels, shots, restarts, offside, events | Unit tests per model. Deterministic replay from seed. ≥ 20× real time. |
| M2 | Controllers for every action type + shape controller | Each controller has a scenario test demonstrating the behavior. |
| M3 | Module 1: pitch control, xT placeholder, lines, lane probabilities, full predicate evaluator | Predicate unit tests. Pitch control validated on synthetic cases (symmetric setups → 0.5). |
| M4 | Play executor | Every starter play runs in its scenario (6.13). Mirror test passes. |
| M5 | Module 2: candidates, hard gate, Hungarian assignment, scoring, preemption. Replay viewer. | Full scripted match runs end-to-end. Viewer shows plays being selected and executed. |
| M6 | Self-play runner (multiprocess), logging, scripted league opponents, sim-derived xT | Generates ≥ 200k decisions. Dataset loader + summary report (play frequency, success rates by play/opponent). |
| M7 | GNN encoder, critic, response model; critic integrated into ranking | Critic beats a per-play-mean baseline on held-out data (lower MSE). Ranking with critic improves EPV vs. without. |
| M8 | Tokenizer, grammar-constrained generator, BC + mutation filtering | ≥ 99% validity. Phase B targets met. |
| M9 | PPO fine-tuning, full league, QD archive, promotion pipeline | Main agent beats all scripted opponents, including the held-out one, on EPV and goal difference. Archive coverage grows. Promoted plays exported for review. |
| M10 | (Optional) GRF adapter; SoccerNet calibration of pass/xG models and critic cross-check | Documented sim-vs-real calibration gaps. |

---

## 15. Repository layout

```
soccer_sim/
  pyproject.toml
  configs/        sim.yaml  ranking.yaml  league.yaml  training.yaml  formations.yaml  xt_placeholder.yaml
  plays/
    offensive/    *.yaml
    defensive/    *.yaml
    promoted/     *.yaml            # generated, pending human review
    CHANGELOG.md
  src/soccer_sim/
    schema/       models.py  predicates.py  targets.py  validate.py  loader.py
    sim/          state.py  physics.py  ball.py  duels.py  shots.py  restarts.py  events.py  env.py  scenarios.py
    controllers/  base.py  on_ball.py  off_ball.py  defensive.py  shape.py
    dashboard/    team_state.py  opponent_model.py  pitch_control.py  xt.py  lines.py  lanes.py  evaluator.py
    ranking/      graph.py  constraints.py  assignment.py  scorer.py  selector.py
    executor/     instance.py  runner.py
    generator/    encoder.py  tokenizer.py  grammar.py  model.py  critic.py  response_model.py  mutate.py
    selfplay/     league.py  pfsp.py  worker.py  runner.py  logging.py  qd_archive.py  promote.py
    eval/         metrics.py  elo.py  reports.py
    viz/          replay.py
  tests/
    fixtures/invalid_plays/
```

---

## 16. Open decisions (defaults chosen; flag if evidence suggests changing)

1. **Simulator:** custom 2D play-level simulator first; GRF adapter later (M10). *Reason:* plays are defined relative to pitch control and use option-level actions, and GRF's low-level action space would require a controller translation layer.
2. **xT source:** placeholder → sim-derived → SoccerNet-calibrated.
3. **Generator family:** transformer decoder first; diffusion as an alternative behind the same interface.
4. **Symmetric self-play:** the main agent plays both sides with shared weights. Revisit if asymmetric roles emerge.
5. **Preempt margin and re-rank interval** (0.02 EPV, 2.0 s): tune in M5 from replays.

When a physics or scoring parameter clearly needs tuning, change it in config and note the reason in a commit message. Don't hardcode fixes.
