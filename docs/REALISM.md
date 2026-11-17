# Realism: diagnosis of the simulator's laws

Realism is a **diagnostic**, not a success criterion (success is achieving chosen objectives and
adapting to changing players). Outcome statistics come from both the simulator's laws and the
teams' behaviour; a team may find a novel, unrealistic way to win, and that is acceptable. But
when a *law* is wrong, teams learn to exploit it, so each large gap is inspected to decide whether
the law or the behaviour is responsible, and only wrong laws are fixed.

Scorecard: `python scripts/realism_report.py --team selector` (continuous games against every
style, per team per 90 minutes, next to approximate real-football ranges); latest in
`reports/realism/<team>/`.

Isolated law tests: `python scripts/law_tests.py` (one factor at a time, no teams or plays).

## Law fixes made (D-056, pool v6)

| Law | Before | After (`scripts/law_tests.py`) |
|---|---|---|
| Pressure on the passer: aim error for every passer, `pressure_deg x pressure` (configs/sim.yaml `pass.noise`) | 20 m pass to a free receiver: 100 / 95 / 96 / 96% completed with no defender / a defender at 4 / 2 / 1 m (the drop came only from the defender chasing the ball, the same at every distance) | 100 / 95 / 90 / 83–86% |
| Blocked shots: an outfield defender near the line of a shot can block it; the ball runs loose (`shot.block`) | never blocked: a 16 m central shot scored 17 / 15 / 13% with 0 / 1 / 3 defenders in the line | blocked 0 / 26–32 / 49–57%; goals 11–16 / 7–10 / 4% |
| Gradual fatigue: capabilities degrade with work, `rate x (1.2 - stamina capability) x (speed / top speed)^2` per second; top speed and acceleration fall by up to 15% and 20%, technique by 5–15% (`fatigue`, soccersim/sim/fatigue.py) | only the short-term stamina: sprinting lowered top speed to 85% at most, recovered within a minute, and jogging cost nothing | shuttle sprints: top speed 95 / 81 / 74% after 1 / 5 / 15 minutes; half speed: 100 / 99 / 97% |

Scenarios now start with the fatigue their match minute implies (about 0.0035 per minute, varying
by player), and capabilities can change over time: a gradual change of any capability, or a
substitution (a fresh player with new capabilities in that slot), set by `Scenario.cap_events`.

## Scorecard of the best selector under the new laws

28 continuous games of 5 minutes (140 simulated minutes) against every style; the selector was
trained under the old laws, so behaviour (how often it shoots, how much it runs) has not adapted
yet. Earlier scorecards used 7 games, which proved far too few: two 7-game samples of the same
team gave 62% and 84% short-pass completion.

| Measure | Simulation | Real (approx.) | Cause |
|---|---|---|---|
| Pass completion (every pass played) | 66% (71% without the pressure law, 67% with neither pressure nor fatigue) | 75–85% | to inspect: likely behaviour (the carrier instinct passes when the pass succeeds at least 55% of the time) and congestion |
| Short passes (< 15 m) | 68% | 85–92% | same |
| Long passes (≥ 30 m) | 46% | 50–62% | about right |
| Completion drop when pressed (opponent < 2 m) | 2 points | 5–15 points | the law now gives 10–15 points in isolation (above); in games, passes under pressure are mostly short and safe |
| Shots / goals | 94 / 5.8 (were 98 / 13) | 10–15 / 1.2–1.6 | behaviour: the selector shoots constantly; retraining under blocked shots should reduce it |
| Shots blocked | 25% | 20–30% | fine |
| xG per shot | 0.06 | 0.09–0.12 | behaviour: many speculative shots |
| Distance per outfield player | 205 m/min | 105–125 m/min | behaviour (shape and pressing movement); running now costs fatigue |
| Fatigue built up per 90 minutes | 1.03 | ~0.3–0.5 at real work rates | follows from the running |
| Tackles won / fouls / ball out (match) | 31 / 18 / 144 | 8–15 / 9–13 / 70–100 | to inspect |

## Scorecard of the best selector (pool v5, old laws, 35 simulated minutes; too small a sample)

| Measure | Simulation | Real (approx.) | Cause |
|---|---|---|---|
| Pass completion (every pass played) | 76% | 75–85% | fine |
| Short passes (< 15 m) | 79% | 85–92% | a little low |
| Long passes (≥ 30 m) | 77% | 50–62% | behaviour: long passes are only tried when the receiver is free (see test 2) |
| Completion drop when pressed (opponent < 2 m) | 2 points | 5–15 points | **law** (test 1) |
| Shots / goals | 98 / 13 | 10–15 / 1.2–1.6 | **law** (no shot blocking) exploited by behaviour (the selector shoots constantly) |
| xG per shot | 0.09 | 0.09–0.12 | fine |
| Distance per outfield player | 200 m/min | 105–125 m/min | **missing law**: running costs almost nothing (no fatigue) |
| Time above 4 m/s / sprinting | 40% / 8% | 12–20% / 1–3% | same |
| Tackles won / fouls / ball out (match) | 33 / 18 / 139 | 8–15 / 9–13 / 70–100 | to inspect; partly the excess running |

An earlier count gave 95% pass completion: it compared completed passes only with intercepted
ones and missed passes lost on the first touch or out of play.

## Isolated tests (the simulator's own pass model, one factor at a time)

1. **Pressure on the passer.** A 20 m ground pass to a free receiver arrives 100% / 100% / 99% /
   99% of the time with no defender / a defender beside the passer at 4 m / 2 m / 1 m. Pressure
   scales the aim error (`noise.angle_base_deg x (1 - passing) x (1 + pressure_gain x pressure)`),
   and for a passer of passing 0.7 the error is about 3° even when pressed. **Wrong law**: in
   real football a pressed pass fails noticeably more often.
2. **Long passes.** A 40 m lofted pass arrives 85% of the time unmarked and about 42% with a
   defender within 6 m of the receiver; a 40 m through ball is cut out whenever a defender is
   within 6 m. Plausible; not a law problem.
3. **Shots.** The simulator does not model blocked shots (`soccersim/executor/shooting.py`); a shot
   through a crowded box is as likely to score as one through an empty one. **Wrong law**: real
   teams block roughly a quarter of shots.

## Still to inspect

- Pass completion, especially short passes: which failures (interceptions, first touch, out of
  play) and whether the carrier instinct's pass threshold is the cause.
- Tackles, fouls and balls out of play, all well above real counts.
