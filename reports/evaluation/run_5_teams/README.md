# Team evaluation

20 scenarios x 7 opponents x 2 sides, continuous 120-second games. Per game, from the team's side; ± is one standard error (a difference beyond about 2 SE is unlikely to be luck).

| Team | xG difference | Goal difference | Shot difference | Games |
|---|---|---|---|---|
| selector | +0.080 ± 0.016 | +0.029 ± 0.023 | +1.14 ± 0.07 | 280 |
| trial_critic | +0.048 ± 0.014 | +0.014 ± 0.021 | +0.93 ± 0.08 | 280 |
| main | +0.022 ± 0.015 | -0.011 ± 0.022 | +0.54 ± 0.08 | 280 |
| library | +0.002 ± 0.013 | -0.004 ± 0.018 | +0.01 ± 0.07 | 280 |

## Paired against `library` (same scenarios, same opponents)

| Team | xG difference minus baseline's | Goal difference minus baseline's | Pairs |
|---|---|---|---|
| selector | +0.078 ± 0.018 | +0.032 ± 0.026 | 280 |
| trial_critic | +0.046 ± 0.017 | +0.018 ± 0.023 | 280 |
| main | +0.020 ± 0.017 | -0.007 ± 0.024 | 280 |

## xG difference per opponent

| Team | chaotic | direct | high_press | low_block_counter | mid_block | possession | wing_play |
|---|---|---|---|---|---|---|---|
| library | +0.02 ± 0.03 | -0.05 ± 0.04 | +0.04 ± 0.03 | -0.03 ± 0.04 | +0.02 ± 0.02 | +0.07 ± 0.04 | -0.04 ± 0.04 |
| selector | +0.09 ± 0.06 | +0.07 ± 0.04 | +0.07 ± 0.04 | +0.04 ± 0.04 | +0.09 ± 0.03 | +0.07 ± 0.03 | +0.13 ± 0.05 |
| main | +0.02 ± 0.04 | -0.04 ± 0.04 | +0.02 ± 0.05 | -0.02 ± 0.05 | +0.10 ± 0.03 | +0.04 ± 0.03 | +0.02 ± 0.03 |
| trial_critic | +0.04 ± 0.05 | +0.04 ± 0.04 | +0.05 ± 0.04 | +0.06 ± 0.04 | +0.01 ± 0.02 | +0.06 ± 0.02 | +0.08 ± 0.04 |
