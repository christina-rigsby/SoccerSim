# Team evaluation

20 scenarios x 7 opponents x 2 sides, continuous 120-second games. Per game, from the team's side; ± is one standard error (a difference beyond about 2 SE is unlikely to be luck).

| Team | xG difference | Goal difference | Shot difference | Games |
|---|---|---|---|---|
| main_latest | +0.062 ± 0.013 | +0.025 ± 0.017 | +1.59 ± 0.11 | 280 |
| selector_latest | +0.061 ± 0.015 | +0.025 ± 0.021 | +1.92 ± 0.09 | 280 |
| trial_critic | +0.030 ± 0.015 | +0.039 ± 0.022 | +1.20 ± 0.09 | 280 |
| library | +0.012 ± 0.012 | +0.021 ± 0.017 | -0.02 ± 0.07 | 280 |

## Paired against `library` (same scenarios, same opponents)

| Team | xG difference minus baseline's | Goal difference minus baseline's | Pairs |
|---|---|---|---|
| main_latest | +0.050 ± 0.017 | +0.004 ± 0.022 | 280 |
| selector_latest | +0.049 ± 0.017 | +0.004 ± 0.026 | 280 |
| trial_critic | +0.018 ± 0.019 | +0.018 ± 0.026 | 280 |

## xG difference per opponent

| Team | chaotic | direct | high_press | low_block_counter | mid_block | possession | wing_play |
|---|---|---|---|---|---|---|---|
| library | +0.01 ± 0.04 | +0.04 ± 0.03 | +0.02 ± 0.04 | -0.01 ± 0.02 | +0.04 ± 0.03 | +0.00 ± 0.02 | -0.01 ± 0.04 |
| selector_latest | +0.00 ± 0.05 | +0.07 ± 0.04 | +0.08 ± 0.04 | +0.07 ± 0.03 | +0.08 ± 0.04 | +0.06 ± 0.03 | +0.06 ± 0.03 |
| main_latest | +0.10 ± 0.04 | +0.03 ± 0.03 | +0.04 ± 0.04 | +0.04 ± 0.03 | +0.11 ± 0.04 | +0.01 ± 0.03 | +0.11 ± 0.04 |
| trial_critic | +0.07 ± 0.04 | +0.03 ± 0.03 | +0.03 ± 0.04 | -0.02 ± 0.04 | +0.01 ± 0.04 | +0.05 ± 0.03 | +0.05 ± 0.05 |
