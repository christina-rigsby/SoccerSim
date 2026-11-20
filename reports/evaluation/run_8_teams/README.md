# Team evaluation

20 scenarios x 7 opponents x 2 sides, continuous 120-second games. Per game, from the team's side; ± is one standard error (a difference beyond about 2 SE is unlikely to be luck).

| Team | xG difference | Goal difference | Shot difference | Games |
|---|---|---|---|---|
| main_latest | +0.089 ± 0.018 | +0.114 ± 0.031 | +0.64 ± 0.11 | 280 |
| library | +0.017 ± 0.016 | -0.007 ± 0.027 | +0.21 ± 0.10 | 280 |
| selector_latest | +0.008 ± 0.015 | +0.029 ± 0.029 | +1.39 ± 0.11 | 280 |

## Paired against `library` (same scenarios, same opponents)

| Team | xG difference minus baseline's | Goal difference minus baseline's | Pairs |
|---|---|---|---|
| main_latest | +0.072 ± 0.023 | +0.121 ± 0.039 | 280 |
| selector_latest | -0.009 ± 0.021 | +0.036 ± 0.037 | 280 |

## xG difference per opponent

| Team | chaotic | direct | high_press | low_block_counter | mid_block | possession | wing_play |
|---|---|---|---|---|---|---|---|
| library | +0.06 ± 0.04 | -0.04 ± 0.04 | -0.02 ± 0.05 | +0.00 ± 0.04 | +0.04 ± 0.04 | +0.04 ± 0.04 | +0.03 ± 0.04 |
| selector_latest | +0.01 ± 0.05 | -0.05 ± 0.04 | +0.07 ± 0.04 | -0.03 ± 0.03 | +0.02 ± 0.04 | +0.03 ± 0.05 | +0.00 ± 0.04 |
| main_latest | +0.00 ± 0.04 | +0.02 ± 0.04 | +0.02 ± 0.05 | +0.06 ± 0.04 | +0.17 ± 0.04 | +0.25 ± 0.06 | +0.11 ± 0.05 |
