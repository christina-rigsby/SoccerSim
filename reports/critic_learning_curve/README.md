# Critic learning curve

Does the critic need more data, a bigger model, or neither? Produced by
`scripts/critic_learning_curve.py` on the pool-v3 Phase A games (13,500 games, 143,378 decisions;
target: possession return). Every run is tested on the same 1,350 held-out games.

**Skill** = `1 - MSE / MSE(per-play average)`: how much better the critic predicts a play's
outcome than simply using that play's average outcome. 0% = no better.

## Robust (Huber) loss, as used by the pipeline (`results.json`, `learning_curve.png`)

| Training games | Small (275k parameters) | Large (1.3M parameters) |
|---|---|---|
| 1,215 (10%) | -3.9% | -4.2% |
| 3,038 (25%) | -1.9% | -4.5% |
| 6,075 (50%) | -0.4% | -4.2% |
| 12,150 (100%) | -1.7% | not run |

The pipeline's own critic (small, 100%, 8 epochs) scored -1.3%.

## Squared-error loss (`loss_mse/`)

| Training games | Skill | Correlation with outcome |
|---|---|---|
| 3,038 (25%) | +0.7% | 0.280 |
| 12,150 (100%) | -0.1% | 0.268 |

The per-play average alone correlates 0.268 with the outcome.

## Conclusions

- **Neither more data nor a bigger model helps.** Gains stop at about half the games, and the
  larger model is worse at every size. Epoch-to-epoch noise is about ±1 point.
- **The Huber loss was hurting.** It aims for each play's typical outcome, but about 1% of
  plays carry a goal (±1) that dominates the average; predicting the per-play median instead of
  the mean scores -7%. Squared-error loss lifts the critic by about 2 points, to the level of the per-play average.
- **The critic learns almost nothing beyond which play was called.** Even on its training
  games it is no better than the per-play average, so it is not memorising; the situation, as
  the critic sees it, barely changes how a play turns out under this target.
