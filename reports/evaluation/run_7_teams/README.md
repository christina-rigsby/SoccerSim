# Team evaluation

20 scenarios x 7 opponents x 2 sides, continuous 120-second games. Per game, from the team's side; ± is one standard error (a difference beyond about 2 SE is unlikely to be luck).

| Team | xG difference | Goal difference | Shot difference | Games |
|---|---|---|---|---|
| main_latest | +0.099 ± 0.017 | +0.082 ± 0.024 | +2.13 ± 0.12 | 280 |
| selector_latest | +0.049 ± 0.014 | +0.014 ± 0.023 | +1.49 ± 0.09 | 280 |
| library | -0.002 ± 0.013 | -0.021 ± 0.019 | +0.01 ± 0.08 | 280 |

## Paired against `library` (same scenarios, same opponents)

| Team | xG difference minus baseline's | Goal difference minus baseline's | Pairs |
|---|---|---|---|
| main_latest | +0.101 ± 0.021 | +0.104 ± 0.030 | 280 |
| selector_latest | +0.051 ± 0.019 | +0.036 ± 0.031 | 280 |

## xG difference per opponent

| Team | chaotic | direct | high_press | low_block_counter | mid_block | possession | wing_play |
|---|---|---|---|---|---|---|---|
| library | -0.03 ± 0.03 | -0.02 ± 0.03 | -0.05 ± 0.04 | -0.01 ± 0.03 | +0.01 ± 0.04 | +0.09 ± 0.03 | +0.00 ± 0.04 |
| selector_latest | +0.00 ± 0.05 | +0.04 ± 0.04 | +0.01 ± 0.03 | +0.04 ± 0.04 | +0.11 ± 0.03 | +0.08 ± 0.03 | +0.06 ± 0.03 |
| main_latest | +0.16 ± 0.05 | +0.05 ± 0.05 | +0.16 ± 0.06 | +0.08 ± 0.04 | +0.07 ± 0.03 | +0.08 ± 0.04 | +0.08 ± 0.04 |
