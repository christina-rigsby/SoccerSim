# Objective success rates

100 fixed situations per objective, against every opponent; 95% Wilson intervals. Headline: the rate against the team's weakest opponent. See soccersim/selfplay/objectives.py.

| Objective | Condition | Team | Overall | Weakest opponent | Beats library against every opponent | Target (weakest) | Met |
|---|---|---|---|---|---|---|---|
| keep_15 | our_forwards_slow | expert@objective | 76% (73%–79%) | 75% (66%–82%) v high_press | yes | 75% | yes |
| keep_15 | our_forwards_slow | library | 29% (26%–32%) | 29% (21%–39%) v chaotic | — | 75% | — |
| keep_15 | their_defence_tiring | expert@objective | 76% (73%–79%) | 76% (67%–83%) v chaotic | yes | 75% | yes |
| keep_15 | their_defence_tiring | library | 26% (23%–30%) | 26% (18%–35%) v chaotic | — | 75% | — |
| shot_60 | our_forwards_slow | expert@objective | 65% (61%–68%) | 52% (42%–62%) v possession | no | 90% | no |
| shot_60 | our_forwards_slow | library | 59% (55%–62%) | 53% (43%–62%) v possession | — | 90% | — |
| shot_60 | their_defence_tiring | expert@objective | 75% (72%–78%) | 69% (59%–77%) v possession | no | 90% | no |
| shot_60 | their_defence_tiring | library | 73% (69%–76%) | 67% (57%–75%) v possession | — | 90% | — |

## Every pairing

| Objective | Condition | Team | Opponent | n | Rate (95%) |
|---|---|---|---|---|---|
| keep_15 | our_forwards_slow | expert@objective | chaotic | 100 | 76% (67%–83%) |
| keep_15 | our_forwards_slow | expert@objective | direct | 100 | 76% (67%–83%) |
| keep_15 | our_forwards_slow | expert@objective | high_press | 100 | 75% (66%–82%) |
| keep_15 | our_forwards_slow | expert@objective | low_block_counter | 100 | 76% (67%–83%) |
| keep_15 | our_forwards_slow | expert@objective | mid_block | 100 | 76% (67%–83%) |
| keep_15 | our_forwards_slow | expert@objective | possession | 100 | 76% (67%–83%) |
| keep_15 | our_forwards_slow | expert@objective | wing_play | 100 | 76% (67%–83%) |
| keep_15 | our_forwards_slow | library | chaotic | 100 | 29% (21%–39%) |
| keep_15 | our_forwards_slow | library | direct | 100 | 29% (21%–39%) |
| keep_15 | our_forwards_slow | library | high_press | 100 | 29% (21%–39%) |
| keep_15 | our_forwards_slow | library | low_block_counter | 100 | 29% (21%–39%) |
| keep_15 | our_forwards_slow | library | mid_block | 100 | 29% (21%–39%) |
| keep_15 | our_forwards_slow | library | possession | 100 | 29% (21%–39%) |
| keep_15 | our_forwards_slow | library | wing_play | 100 | 29% (21%–39%) |
| keep_15 | their_defence_tiring | expert@objective | chaotic | 100 | 76% (67%–83%) |
| keep_15 | their_defence_tiring | expert@objective | direct | 100 | 76% (67%–83%) |
| keep_15 | their_defence_tiring | expert@objective | high_press | 100 | 79% (70%–86%) |
| keep_15 | their_defence_tiring | expert@objective | low_block_counter | 100 | 76% (67%–83%) |
| keep_15 | their_defence_tiring | expert@objective | mid_block | 100 | 76% (67%–83%) |
| keep_15 | their_defence_tiring | expert@objective | possession | 100 | 76% (67%–83%) |
| keep_15 | their_defence_tiring | expert@objective | wing_play | 100 | 76% (67%–83%) |
| keep_15 | their_defence_tiring | library | chaotic | 100 | 26% (18%–35%) |
| keep_15 | their_defence_tiring | library | direct | 100 | 26% (18%–35%) |
| keep_15 | their_defence_tiring | library | high_press | 100 | 26% (18%–35%) |
| keep_15 | their_defence_tiring | library | low_block_counter | 100 | 26% (18%–35%) |
| keep_15 | their_defence_tiring | library | mid_block | 100 | 26% (18%–35%) |
| keep_15 | their_defence_tiring | library | possession | 100 | 27% (19%–36%) |
| keep_15 | their_defence_tiring | library | wing_play | 100 | 27% (19%–36%) |
| shot_60 | our_forwards_slow | expert@objective | chaotic | 100 | 65% (55%–74%) |
| shot_60 | our_forwards_slow | expert@objective | direct | 100 | 67% (57%–75%) |
| shot_60 | our_forwards_slow | expert@objective | high_press | 100 | 74% (65%–82%) |
| shot_60 | our_forwards_slow | expert@objective | low_block_counter | 100 | 74% (65%–82%) |
| shot_60 | our_forwards_slow | expert@objective | mid_block | 100 | 55% (45%–64%) |
| shot_60 | our_forwards_slow | expert@objective | possession | 100 | 52% (42%–62%) |
| shot_60 | our_forwards_slow | expert@objective | wing_play | 100 | 68% (58%–76%) |
| shot_60 | our_forwards_slow | library | chaotic | 100 | 56% (46%–65%) |
| shot_60 | our_forwards_slow | library | direct | 100 | 59% (49%–68%) |
| shot_60 | our_forwards_slow | library | high_press | 100 | 64% (54%–73%) |
| shot_60 | our_forwards_slow | library | low_block_counter | 100 | 63% (53%–72%) |
| shot_60 | our_forwards_slow | library | mid_block | 100 | 58% (48%–67%) |
| shot_60 | our_forwards_slow | library | possession | 100 | 53% (43%–62%) |
| shot_60 | our_forwards_slow | library | wing_play | 100 | 59% (49%–68%) |
| shot_60 | their_defence_tiring | expert@objective | chaotic | 100 | 77% (68%–84%) |
| shot_60 | their_defence_tiring | expert@objective | direct | 100 | 79% (70%–86%) |
| shot_60 | their_defence_tiring | expert@objective | high_press | 100 | 79% (70%–86%) |
| shot_60 | their_defence_tiring | expert@objective | low_block_counter | 100 | 75% (66%–82%) |
| shot_60 | their_defence_tiring | expert@objective | mid_block | 100 | 77% (68%–84%) |
| shot_60 | their_defence_tiring | expert@objective | possession | 100 | 69% (59%–77%) |
| shot_60 | their_defence_tiring | expert@objective | wing_play | 100 | 72% (63%–80%) |
| shot_60 | their_defence_tiring | library | chaotic | 100 | 78% (69%–85%) |
| shot_60 | their_defence_tiring | library | direct | 100 | 72% (63%–80%) |
| shot_60 | their_defence_tiring | library | high_press | 100 | 72% (63%–80%) |
| shot_60 | their_defence_tiring | library | low_block_counter | 100 | 71% (61%–79%) |
| shot_60 | their_defence_tiring | library | mid_block | 100 | 68% (58%–76%) |
| shot_60 | their_defence_tiring | library | possession | 100 | 67% (57%–75%) |
| shot_60 | their_defence_tiring | library | wing_play | 100 | 80% (71%–87%) |
