# Objective success rates

20 fixed situations per objective, against every opponent; 95% Wilson intervals. Headline: the rate against the team's weakest opponent. See soccersim/selfplay/objectives.py.

| Objective | Condition | Team | Overall | Weakest opponent | Beats library against every opponent | Target (weakest) | Met |
|---|---|---|---|---|---|---|---|
| chance_180 | fresh | library | 39% (31%–47%) | 25% (11%–47%) v direct | — | 60% | — |
| chance_180 | fresh | lookahead_fast@objective | 68% (60%–75%) | 65% (43%–82%) v direct | yes | 60% | yes |
| protect_300 | fresh | library | 81% (73%–86%) | 75% (53%–89%) v chaotic | — | 90% | — |
| protect_300 | fresh | lookahead_fast@objective | 73% (65%–80%) | 60% (39%–78%) v direct | no | 90% | no |

## Every pairing

| Objective | Condition | Team | Opponent | n | Rate (95%) |
|---|---|---|---|---|---|
| chance_180 | fresh | library | chaotic | 20 | 40% (22%–61%) |
| chance_180 | fresh | library | direct | 20 | 25% (11%–47%) |
| chance_180 | fresh | library | high_press | 20 | 25% (11%–47%) |
| chance_180 | fresh | library | low_block_counter | 20 | 30% (15%–52%) |
| chance_180 | fresh | library | mid_block | 20 | 60% (39%–78%) |
| chance_180 | fresh | library | possession | 20 | 55% (34%–74%) |
| chance_180 | fresh | library | wing_play | 20 | 35% (18%–57%) |
| chance_180 | fresh | lookahead_fast@objective | chaotic | 20 | 75% (53%–89%) |
| chance_180 | fresh | lookahead_fast@objective | direct | 20 | 65% (43%–82%) |
| chance_180 | fresh | lookahead_fast@objective | high_press | 20 | 65% (43%–82%) |
| chance_180 | fresh | lookahead_fast@objective | low_block_counter | 20 | 65% (43%–82%) |
| chance_180 | fresh | lookahead_fast@objective | mid_block | 20 | 65% (43%–82%) |
| chance_180 | fresh | lookahead_fast@objective | possession | 20 | 65% (43%–82%) |
| chance_180 | fresh | lookahead_fast@objective | wing_play | 20 | 75% (53%–89%) |
| protect_300 | fresh | library | chaotic | 20 | 75% (53%–89%) |
| protect_300 | fresh | library | direct | 20 | 75% (53%–89%) |
| protect_300 | fresh | library | high_press | 20 | 80% (58%–92%) |
| protect_300 | fresh | library | low_block_counter | 20 | 85% (64%–95%) |
| protect_300 | fresh | library | mid_block | 20 | 80% (58%–92%) |
| protect_300 | fresh | library | possession | 20 | 85% (64%–95%) |
| protect_300 | fresh | library | wing_play | 20 | 85% (64%–95%) |
| protect_300 | fresh | lookahead_fast@objective | chaotic | 20 | 90% (70%–97%) |
| protect_300 | fresh | lookahead_fast@objective | direct | 20 | 60% (39%–78%) |
| protect_300 | fresh | lookahead_fast@objective | high_press | 20 | 70% (48%–85%) |
| protect_300 | fresh | lookahead_fast@objective | low_block_counter | 20 | 65% (43%–82%) |
| protect_300 | fresh | lookahead_fast@objective | mid_block | 20 | 75% (53%–89%) |
| protect_300 | fresh | lookahead_fast@objective | possession | 20 | 80% (58%–92%) |
| protect_300 | fresh | lookahead_fast@objective | wing_play | 20 | 70% (48%–85%) |
