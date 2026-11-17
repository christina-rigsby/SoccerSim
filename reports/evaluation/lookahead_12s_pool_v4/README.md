# Team evaluation

20 scenarios x 7 opponents x 2 sides, continuous 120-second games. Per game, from the team's side; ± is one standard error (a difference beyond about 2 SE is unlikely to be luck).

| Team | xG difference | Goal difference | Shot difference | Games |
|---|---|---|---|---|
| lookahead_fair_8x6_12s | +0.141 ± 0.015 | +0.136 ± 0.027 | +1.09 ± 0.09 | 280 |
| library | +0.002 ± 0.013 | +0.007 ± 0.021 | +0.11 ± 0.08 | 280 |

## Paired against `library` (same scenarios, same opponents)

| Team | xG difference minus baseline's | Goal difference minus baseline's | Pairs |
|---|---|---|---|
| lookahead_fair_8x6_12s | +0.140 ± 0.020 | +0.129 ± 0.035 | 280 |

## xG difference per opponent

| Team | chaotic | direct | high_press | low_block_counter | mid_block | possession | wing_play |
|---|---|---|---|---|---|---|---|
| library | +0.02 ± 0.02 | -0.09 ± 0.04 | -0.02 ± 0.04 | -0.06 ± 0.03 | +0.08 ± 0.03 | +0.07 ± 0.03 | -0.00 ± 0.04 |
| lookahead_fair_8x6_12s | +0.18 ± 0.04 | +0.12 ± 0.04 | +0.11 ± 0.03 | +0.09 ± 0.03 | +0.12 ± 0.04 | +0.22 ± 0.04 | +0.15 ± 0.04 |
