# Realism: diagnosis of the simulator's laws

Realism is a **diagnostic**, not a success criterion (success is achieving chosen objectives and
adapting to changing players). Outcome statistics come from both the simulator's laws and the
teams' behaviour; a team may find a novel, unrealistic way to win, and that is acceptable. But
when a *law* is wrong, teams learn to exploit it, so each large gap is inspected to decide whether
the law or the behaviour is responsible, and only wrong laws are fixed.

Scorecard: `python scripts/realism_report.py --team selector` (continuous games against every
style, per team per 90 minutes, next to approximate real-football ranges); latest in
`reports/realism/<team>/`.

## Scorecard of the best selector (pool v5, 35 simulated minutes)

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

## Planned fixes (batched with fatigue and substitutions, then one retraining)

- Pressure adds aim error for every passer, not only weak ones.
- Shots can be blocked by outfield defenders in the shooting cone near the ball.
- Fatigue: capabilities degrade gradually with effort, so constant running has a cost.
