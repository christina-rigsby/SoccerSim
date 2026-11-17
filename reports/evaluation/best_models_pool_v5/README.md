# Team evaluation

20 scenarios x 7 opponents x 2 sides, continuous 120-second games. Per game, from the team's side; ± is one standard error (a difference beyond about 2 SE is unlikely to be luck).

| Team | xG difference | Goal difference | Shot difference | Games |
|---|---|---|---|---|
| selector_latest | +0.080 ± 0.016 | +0.029 ± 0.023 | +1.14 ± 0.07 | 280 |
| main | +0.048 ± 0.014 | +0.050 ± 0.027 | +0.94 ± 0.09 | 280 |
| main_latest | +0.022 ± 0.015 | -0.011 ± 0.022 | +0.54 ± 0.08 | 280 |
| library | +0.002 ± 0.013 | -0.004 ± 0.018 | +0.01 ± 0.07 | 280 |
| selector | -0.016 ± 0.008 | +0.004 ± 0.016 | +0.16 ± 0.06 | 280 |

## Paired against `library` (same scenarios, same opponents)

| Team | xG difference minus baseline's | Goal difference minus baseline's | Pairs |
|---|---|---|---|
| selector_latest | +0.078 ± 0.018 | +0.032 ± 0.026 | 280 |
| main | +0.046 ± 0.016 | +0.054 ± 0.028 | 280 |
| main_latest | +0.020 ± 0.017 | -0.007 ± 0.024 | 280 |
| selector | -0.018 ± 0.014 | +0.007 ± 0.020 | 280 |

## xG difference per opponent

| Team | chaotic | direct | high_press | low_block_counter | mid_block | possession | wing_play |
|---|---|---|---|---|---|---|---|
| library | +0.02 ± 0.03 | -0.05 ± 0.04 | +0.04 ± 0.03 | -0.03 ± 0.04 | +0.02 ± 0.02 | +0.07 ± 0.04 | -0.04 ± 0.04 |
| selector | -0.01 ± 0.02 | -0.04 ± 0.02 | -0.04 ± 0.02 | -0.05 ± 0.03 | -0.00 ± 0.00 | +0.03 ± 0.02 | -0.00 ± 0.02 |
| selector_latest | +0.09 ± 0.06 | +0.07 ± 0.04 | +0.07 ± 0.04 | +0.04 ± 0.04 | +0.09 ± 0.03 | +0.07 ± 0.03 | +0.13 ± 0.05 |
| main | +0.05 ± 0.03 | +0.01 ± 0.04 | +0.11 ± 0.05 | -0.01 ± 0.05 | +0.04 ± 0.01 | +0.09 ± 0.02 | +0.04 ± 0.04 |
| main_latest | +0.02 ± 0.04 | -0.04 ± 0.04 | +0.02 ± 0.05 | -0.02 ± 0.05 | +0.10 ± 0.03 | +0.04 ± 0.03 | +0.02 ± 0.03 |
