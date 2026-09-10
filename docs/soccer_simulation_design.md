# Soccer Simulation Design Notes

## 1. Overall Architecture

Three-module decomposition, with a feedback/replanning loop tying them together:

1. **Information Dashboard** — tracks team state, opponent model, game state, and a live space/geometry layer.
2. **Play Ranking System** — a weighted graph over objectives, strategies, plays, constraints, player capabilities, and players. Total path weight (plus an assignment-solve step for player-to-role matching) ranks candidate plays.
3. **AI/ML Play Generator** — comes online when no pre-defined play scores above threshold; generates novel candidate plays and inserts them into the same ranking graph as new Play nodes, so there is one selection mechanism, not two separate branches.

**Replanning cadence:** re-evaluate feasibility/ranking every ~0.5–1s of simulated time, or on trigger events (e.g., a defender closing a passing lane faster than expected). Plans are receding-horizon, not one-shot — be willing to abort mid-play and reselect.

---

## 2. Dashboard: What to Track

### Team state (self)
- Per player: position, velocity/heading, fatigue/stamina, role, current action, availability (injured/carded), speed/accel capability profile
- Formation shape: centroid, width, depth, compactness
- Possession status, ball carrier, pressure on ball carrier

### Opponent model (grows over time)
- Current formation and shape (defensive line height, width, compactness)
- Inferred marking scheme: man-to-man vs. zonal, with zone boundaries if zonal
- Pressing triggers: what provokes a press, press intensity, press trap tendencies
- Defensive line behavior: offside trap usage, line-breaking susceptibility
- Individual defender tendencies: preferred foot to jockey onto, recovery speed, tackling aggression, 1v1 win rate
- Historical play patterns against similar objectives/strategies — a running "book" on the opponent, updated after every possession
- Set-piece behavior (marking assignments on corners/free kicks)

### Game state
- Score, time remaining, phase (open play, transition, set piece, kickoff)
- Field zone of play, ball state (in flight, on ground, contested)

### Space/geometry layer
This is the interface between "what's happening" and "what play to run" — objectives, strategies, and waypoints should reference this layer rather than raw coordinates.
- Pitch control / dominant-region map (Voronoi-style — who reaches a point first)
- Passing lane availability (open lanes vs. covered, and by whom)
- Expected threat (xT) surface — value of possession at each pitch location

---

## 3. Objective → Strategy → Play → Action Taxonomy

### Objectives
- Score
- Progress ball into final third
- Regain possession
- Retain possession / run clock
- Prevent goal
- Convert set piece
- Defend set piece

### Strategies (selected based on opponent model + game state)

**Under "Score":**
- Counter-attack (exploit opponent transition disorganization)
- Possession buildup through midfield
- Wing overload → cross
- Direct/long-ball to target forward
- High press → win ball in attacking third → immediate shot

**Under "Regain possession":**
- High press (win it near their goal)
- Mid-block (compact, invite them forward, win it in transition)
- Low block (defend deep, counter after regain)

### Plays (concrete instantiations of a strategy, given current opponent shape)

**Under "Wing overload":**
- Overlap: fullback overlaps winger, winger cuts inside, cross from overlap runner
- Underlap: fullback runs inside channel, winger holds width, cutback
- Switch-and-cross: quick switch to weak-side wing where opponent is underloaded, first-time cross

**Under "Counter-attack":**
- Direct vertical: win ball → immediate long pass to advanced forward making a run behind the line
- 3-pass counter: win ball → outlet pass to midfielder → forward pass to winger in space → cross/shot

**Under "High press":**
- Trigger press: initiated on backpass or sideways pass near opponent box
- Trap press: force ball into a pre-identified low-value zone (e.g., touchline) where numbers overload

Each play decomposes into per-player **waypoint + action sequences**, timed/triggered relative to events (ball reaches point X, defender crosses threshold Y) rather than fixed clock time.

### Waypoints relative to opponents

Formalize waypoints using the pitch-control layer rather than raw opponent coordinates, e.g.:
- Point of maximum pitch-control gain along the flank
- Midpoint of the gap between CB and fullback
- N meters behind the last defender's line, in the channel
- Edge of the nearest defender's cover shadow

This makes plays generalize across opponent formations automatically, since geometry is recomputed live.

### Action vocabulary

**On-ball:**
- `pass(target, type=ground|lofted|through)`
- `cross(target_zone)`
- `shoot(target)`
- `dribble(waypoint)`
- `shield(pressure_source)`
- `clear()`
- `header(target)`
- `first_touch(direction)`

**Off-ball (movement/positioning):**
- `move_to(waypoint)`
- `run_behind(defensive_line)` — checking run
- `overlap_run(teammate)`
- `underlap_run(teammate)`
- `decoy_run(waypoint)` — draw a defender away
- `hold_position()`
- `create_width()` / `create_depth()`
- `call_for_ball()`

**Defensive:**
- `mark_man(opponent_id)`
- `mark_zone(zone_id)`
- `press(target)`
- `intercept_lane(passing_lane)`
- `tackle(opponent_id)`
- `jockey(opponent_id)` — delay without committing
- `cover_shadow(passing_lane)` — body position blocking a lane while pressuring
- `track_run(opponent_id)`
- `step_up(offside_trap)`

---

## 4. Ranking System: Weighted Graph

### Node/edge schema

```
Objective --(strategic fit)--> Strategy
Strategy  --(applicability given opponent state)--> Play
Play      --(requires)--> RoleRequirement (e.g. "fast winger")
RoleRequirement --(capability match)--> Player
Play      --(violates / satisfies)--> Constraint
```

### Two-stage scoring (not a single path problem)

A Play needs a *set* of players filling distinct role slots simultaneously — this is an assignment problem, not a path problem.

1. **Path weight**: Objective → Strategy → Play → Constraints (single path — straightforward sum).
2. **Assignment cost**: best one-to-one mapping of available players onto the play's role slots, solved via bipartite matching (Hungarian / Kuhn–Munkres) using capability-match edge weights as the cost matrix.

**Total play score** = path weight (1) combined with assignment cost (2).

### Weight algebra

Pick one consistent semantics up front:
- **Costs** (lower = better, sum = total cost, shortest-path), or
- **Log-probabilities** (sum = joint log-likelihood; exponentiate at the end for a calibrated "P(play succeeds)" — cleanest if edge weights are trained independently from different data sources), or
- **Utilities** (higher = better, net value, negative weights allowed for violations).

If edge types are genuinely incommensurable (e.g., injury risk vs. expected xT gain), consider a small weight *vector* per edge with Pareto-ranking over top candidates instead of collapsing to one scalar.

### Weights are functions, not constants

Recompute weights each replanning epoch from live state:
- Strategy→Play weight depends on live opponent shape (pull from pitch-control/opponent-model layer)
- RoleRequirement→Player weight depends on live fatigue, not just baseline capability
- Play→Constraint weight depends on current game state (score/time)

Since Objective→Strategy→Play is a small DAG, full DP/topological evaluation per epoch is cheap — no need for general shortest-path search. The expensive part is the assignment step, but Hungarian algorithm at ~11 roles is trivial.

### Integration with the ML generator (module 3)

When no pre-defined play scores above threshold: the generator produces candidate trajectories, a critic network scores them, and each is inserted as a **new Play node** with edges computed by the critic. It then competes in the same ranking pass as pre-defined plays — "is this novel play good" reduces to "does it outrank the best pre-defined play." Critic output must be expressed in the same units as the soft-penalty sum below so the comparison is valid.

---

## 5. Constraints

Split into **hard** (prune — binary pass/fail) and **soft** (penalty — feeds the weight sum). Test: *is violating this ever acceptable if the alternative is worse?* If yes → soft. If no → hard.

Run hard constraints as a cheap pre-filter before computing path weights or solving the assignment problem.

### Hard constraints

**Kinematic / physical feasibility**
- `max_speed`: can the assigned player reach each waypoint by its required time given top speed + acceleration (trapezoidal velocity model)
- `pitch_bounds`: every waypoint inside the field of play
- `collision`: no two teammates' paths require occupying the same space at the same time (min separation buffer)
- `single_ball`: only one player can execute a ball-touching action at a given instant

**Rules of the game**
- `offside`: any `run_behind`/receiving waypoint beyond the second-last defender at the moment of the pass is invalid
- `player_count`: play can't require more outfield players than currently available (accounting for red cards)
- `possession_state`: plays requiring possession can't be selected without the ball, and vice versa

**Roster availability**
- `eligibility`: required role can't be filled by an injured/suspended/fouled-out player
- `min_role_coverage`: if a play requires a specialist role and no player meets the minimum capability threshold, the play is infeasible regardless of assignment cost (distinct from "role filled but poorly matched," which is soft)

**Game-state legality**
- `time_remaining`: plays with expected duration exceeding time left in the half/match are invalid
- `set_piece_context`: open-play plays can't be selected during a dead-ball restart, and vice versa

### Soft constraints

**Risk exposure**
- `counter_risk`: penalize plays leaving defensive shape exposed if possession is lost; scales with number of out-of-position defenders and their recovery time
- `turnover_cost_weighted_by_zone`: losing the ball in your own third costs more than in theirs — penalty is a function of *where* the riskiest action occurs
- `overcommitment`: penalize plays needing >N players forward of the ball simultaneously, scaled by score/time context

**Fatigue / load management**
- `player_fatigue_cost`: implement as a degradation of effective capability score in the RoleRequirement→Player edge (not a flat penalty) — penalizes assigning high-sprint-demand roles to already-fatigued players
- `injury_risk`: mild penalty for high-intensity actions assigned to a player carrying a knock

**Tactical fit / opponent exploitation**
- `predictability_penalty`: decaying penalty proportional to recent-usage count of a given play against similar opponent situations — encourages diversification over a match
- `mismatch_bonus`: reward (negative penalty) for plays targeting a specific weak defender identified in the opponent model — direct feed from opponent-model data into play ranking

**Game-state alignment**
- `score_time_alignment`: penalize high-risk strategies (e.g., all-out press) when protecting a narrow lead late, and penalize low-tempo strategies when chasing a goal late — a function of (score differential, time remaining) → penalty multiplier per strategy type
- `momentum` (optional): slight bonus for strategies matching current momentum (e.g., avoid switching to slow buildup immediately after winning the ball high up the pitch)

**Execution confidence**
- `historical_success_rate`: penalize/reward based on this play's empirical success rate for this team — the feedback loop; should dominate over time as data accumulates
- `role_familiarity`: penalize assigning a player to a role/play they haven't practiced, if tracked

**Chain dependency risk**
- `chain_depth_penalty`: plays with long chains of sequential dependent actions (A must complete before B starts) are riskier than plays with parallel independent actions — more sequential handoffs means more chances for opponent disruption to break the play mid-execution. Compute directly from the play's internal action-dependency graph.

### Implementation note

Give every soft constraint a name, a scalar weight/coefficient, and a pure function of `(state, candidate_play, assignment)` — rather than hardcoding penalty values. Tune coefficients via the RL fine-tuning loop (below) or grid search against simulated match outcomes.

---

## 6. AI/ML Fallback (Module 3)

Triggered when no pre-defined play scores above threshold in the ranking system.

### Data source: SoccerNet
- **SoccerNet-Tracking**: player/ball bounding boxes and trajectories from broadcast video — raw motion data. Note: broadcast-camera-derived tracking has calibration noise and can miss off-screen players; treat as noisy-continuous, not ground truth.
- **SoccerNet-GSR (Game State Reconstruction)**: unifies tracking + role/team/jersey identification into structured per-frame game states — closer to the desired training input than raw tracking.
- **SoccerNet Action Spotting**: temporal event labels (pass, shot, tackle, etc.) — useful for segmenting continuous video into discrete "plays."
- For cleaner full-pitch tracking later: Skillcorner / StatsBomb 360 are professional-grade alternatives, but SoccerNet is open and fine for prototyping.

### Architecture

1. **State representation**: graph per frame — nodes = 22 players + ball; features = (position, velocity, role, team, fatigue proxy); edges = spatial relationships (distance, passing-lane visibility). Encode with a GNN or set transformer for a permutation-invariant state embedding.

2. **Segment SoccerNet tracking into "plays"** using action-spotting labels as boundaries (possession-start to shot/loss-of-possession = one play). Heuristically label each segment's objective/strategy (rule-based: ended in a shot from a cross → "wing overload"; followed a turnover in the attacking third → "counter-attack"; etc.). Produces `(state, objective/strategy label, trajectory)` tuples for supervised pretraining.

3. **Play generator**: conditional sequence model — transformer decoder or diffusion model — taking `(current graph state, objective embedding, strategy embedding, opponent-model features)` and outputting per-player waypoint sequences. Diffusion models handle multimodality well (there are usually several plausible good plays, not one deterministic answer), matching approaches used in recent multi-agent sports-trajectory-generation research (e.g., basketball play generation).

4. **Feasibility/value critic**: separate network predicting `P(success | state, candidate play)`, trained on labeled outcomes (did the segment lead to a shot/goal/regained possession) plus simulated rollouts.

5. **RL fine-tuning loop**: pretrain the generator via imitation learning on SoccerNet segments, then fine-tune via self-play in a physics-approximate simulator (Google Research Football is the standard open-source option, or a lightweight custom simulator built on the pitch-control layer). Reward = objective achieved (goal, progressed into final third, regained possession) minus penalties (offside, out-of-bounds waypoints, exceeding kinematic limits, plays flagged infeasible by the critic).

6. **At runtime**: sample N candidate plays from the generator conditioned on live state, score with the critic, filter by hard constraints (can a player physically reach that waypoint in time; is the pass lane actually open right now), and execute the top-ranked feasible play — replanning on the same receding-horizon cadence as the ranking system.

### Suggested build order
Get the pitch-control/space layer and the feasibility critic working first. Everything else (the ranking system's constraint checks, the generator's candidate ranking, even a naive rule-based module-3 fallback before building the generative model) depends on having a good "is this good for us right now" scoring function. Validate modules 1 and 2 fully with hand-authored plays before investing in the generative model.
