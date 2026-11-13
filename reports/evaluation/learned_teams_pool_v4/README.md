# Team evaluation

20 scenarios x 7 opponents x 2 sides, continuous 120-second games. Per game, from the team's side; ± is one standard error (a difference beyond about 2 SE is unlikely to be luck).

| Team | xG difference | Goal difference | Shot difference | Games |
|---|---|---|---|---|
| selector | +0.108 ± 0.017 | +0.100 ± 0.027 | +1.04 ± 0.09 | 280 |
| main | +0.102 ± 0.014 | +0.071 ± 0.027 | +1.26 ± 0.10 | 280 |
| library_critic | +0.022 ± 0.011 | +0.004 ± 0.019 | +0.28 ± 0.08 | 280 |
| library | +0.002 ± 0.013 | +0.007 ± 0.021 | +0.11 ± 0.08 | 280 |

## Paired against `library` (same scenarios, same opponents)

| Team | xG difference minus baseline's | Goal difference minus baseline's | Pairs |
|---|---|---|---|
| selector | +0.106 ± 0.022 | +0.093 ± 0.034 | 280 |
| main | +0.101 ± 0.019 | +0.064 ± 0.033 | 280 |
| library_critic | +0.021 ± 0.017 | -0.004 ± 0.027 | 280 |

## xG difference per opponent

| Team | chaotic | direct | high_press | low_block_counter | mid_block | possession | wing_play |
|---|---|---|---|---|---|---|---|
| library | +0.02 ± 0.02 | -0.09 ± 0.04 | -0.02 ± 0.04 | -0.06 ± 0.03 | +0.08 ± 0.03 | +0.07 ± 0.03 | -0.00 ± 0.04 |
| library_critic | +0.03 ± 0.03 | -0.02 ± 0.03 | -0.00 ± 0.03 | -0.00 ± 0.03 | +0.07 ± 0.02 | +0.04 ± 0.03 | +0.04 ± 0.03 |
| selector | +0.15 ± 0.05 | +0.09 ± 0.05 | +0.15 ± 0.05 | +0.11 ± 0.04 | +0.08 ± 0.03 | +0.05 ± 0.04 | +0.13 ± 0.05 |
| main | +0.11 ± 0.04 | +0.12 ± 0.04 | +0.15 ± 0.04 | +0.06 ± 0.03 | +0.06 ± 0.03 | +0.09 ± 0.03 | +0.13 ± 0.04 |
