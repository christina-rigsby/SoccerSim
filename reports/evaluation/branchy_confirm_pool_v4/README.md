# Team evaluation

40 scenarios x 7 opponents x 2 sides, continuous 120-second games. Per game, from the team's side; ± is one standard error (a difference beyond about 2 SE is unlikely to be luck).

| Team | xG difference | Goal difference | Shot difference | Games |
|---|---|---|---|---|
| library+branchy+prune_failing | +0.025 ± 0.010 | +0.018 ± 0.014 | +0.05 ± 0.05 | 560 |
| library | +0.000 ± 0.009 | -0.007 ± 0.017 | +0.11 ± 0.06 | 560 |
| library+branchy | -0.004 ± 0.010 | +0.009 ± 0.014 | +0.09 ± 0.06 | 560 |

## Paired against `library` (same scenarios, same opponents)

| Team | xG difference minus baseline's | Goal difference minus baseline's | Pairs |
|---|---|---|---|
| library+branchy+prune_failing | +0.025 ± 0.012 | +0.025 ± 0.021 | 560 |
| library+branchy | -0.004 ± 0.011 | +0.016 ± 0.022 | 560 |

## xG difference per opponent

| Team | chaotic | direct | high_press | low_block_counter | mid_block | possession | wing_play |
|---|---|---|---|---|---|---|---|
| library | +0.00 ± 0.03 | -0.04 ± 0.03 | +0.02 ± 0.03 | -0.02 ± 0.02 | +0.00 ± 0.02 | +0.03 ± 0.01 | +0.01 ± 0.02 |
| library+branchy | +0.02 ± 0.03 | -0.02 ± 0.02 | -0.01 ± 0.03 | -0.06 ± 0.03 | -0.03 ± 0.02 | +0.05 ± 0.02 | +0.02 ± 0.03 |
| library+branchy+prune_failing | +0.05 ± 0.03 | +0.00 ± 0.01 | +0.04 ± 0.03 | -0.02 ± 0.01 | +0.03 ± 0.03 | +0.04 ± 0.02 | +0.03 ± 0.03 |
