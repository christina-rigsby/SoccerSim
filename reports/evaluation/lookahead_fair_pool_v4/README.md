# Team evaluation

20 scenarios x 7 opponents x 2 sides, continuous 120-second games. Per game, from the team's side; ± is one standard error (a difference beyond about 2 SE is unlikely to be luck).

| Team | xG difference | Goal difference | Shot difference | Games |
|---|---|---|---|---|
| lookahead_fair | +0.107 ± 0.016 | +0.079 ± 0.027 | +0.48 ± 0.09 | 280 |
| library | +0.002 ± 0.013 | +0.007 ± 0.021 | +0.11 ± 0.08 | 280 |

## Paired against `library` (same scenarios, same opponents)

| Team | xG difference minus baseline's | Goal difference minus baseline's | Pairs |
|---|---|---|---|
| lookahead_fair | +0.106 ± 0.021 | +0.071 ± 0.036 | 280 |

## xG difference per opponent

| Team | chaotic | direct | high_press | low_block_counter | mid_block | possession | wing_play |
|---|---|---|---|---|---|---|---|
| library | +0.02 ± 0.02 | -0.09 ± 0.04 | -0.02 ± 0.04 | -0.06 ± 0.03 | +0.08 ± 0.03 | +0.07 ± 0.03 | -0.00 ± 0.04 |
| lookahead_fair | +0.11 ± 0.05 | +0.07 ± 0.04 | +0.15 ± 0.04 | +0.07 ± 0.04 | +0.10 ± 0.04 | +0.13 ± 0.03 | +0.14 ± 0.05 |
