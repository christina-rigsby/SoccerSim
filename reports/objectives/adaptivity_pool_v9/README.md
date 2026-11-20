# Objective success rates

100 fixed situations per objective, against every opponent; 95% Wilson intervals. Headline: the rate against the team's weakest opponent. See soccersim/selfplay/objectives.py.

| Objective | Condition | Team | Overall | Weakest opponent | Beats library against every opponent | Target (weakest) | Met |
|---|---|---|---|---|---|---|---|
| keep_15 | our_forwards_slow | library | 29% (26%–32%) | 29% (21%–39%) v chaotic | — | 75% | — |
| keep_15 | our_forwards_slow | main_latest | 33% (29%–36%) | 32% (24%–42%) v high_press | yes | 75% | no |
| keep_15 | our_forwards_slow | selector_latest | 43% (39%–47%) | 43% (34%–53%) v chaotic | yes | 75% | no |
| keep_15 | their_defence_tiring | library | 26% (23%–30%) | 26% (18%–35%) v chaotic | — | 75% | — |
| keep_15 | their_defence_tiring | main_latest | 30% (27%–33%) | 30% (22%–40%) v chaotic | yes | 75% | no |
| keep_15 | their_defence_tiring | selector_latest | 37% (34%–41%) | 37% (28%–47%) v chaotic | yes | 75% | no |
| shot_60 | our_forwards_slow | library | 59% (55%–62%) | 53% (43%–62%) v possession | — | 90% | — |
| shot_60 | our_forwards_slow | main_latest | 66% (63%–70%) | 64% (54%–73%) v possession | yes | 90% | no |
| shot_60 | our_forwards_slow | selector_latest | 76% (72%–79%) | 67% (57%–75%) v possession | yes | 90% | no |
| shot_60 | their_defence_tiring | library | 73% (69%–76%) | 67% (57%–75%) v possession | — | 90% | — |
| shot_60 | their_defence_tiring | main_latest | 78% (75%–81%) | 75% (66%–82%) v direct | yes | 90% | no |
| shot_60 | their_defence_tiring | selector_latest | 80% (77%–83%) | 72% (63%–80%) v possession | yes | 90% | no |

## Every pairing

| Objective | Condition | Team | Opponent | n | Rate (95%) |
|---|---|---|---|---|---|
| keep_15 | our_forwards_slow | library | chaotic | 100 | 29% (21%–39%) |
| keep_15 | our_forwards_slow | library | direct | 100 | 29% (21%–39%) |
| keep_15 | our_forwards_slow | library | high_press | 100 | 29% (21%–39%) |
| keep_15 | our_forwards_slow | library | low_block_counter | 100 | 29% (21%–39%) |
| keep_15 | our_forwards_slow | library | mid_block | 100 | 29% (21%–39%) |
| keep_15 | our_forwards_slow | library | possession | 100 | 29% (21%–39%) |
| keep_15 | our_forwards_slow | library | wing_play | 100 | 29% (21%–39%) |
| keep_15 | our_forwards_slow | main_latest | chaotic | 100 | 33% (25%–43%) |
| keep_15 | our_forwards_slow | main_latest | direct | 100 | 33% (25%–43%) |
| keep_15 | our_forwards_slow | main_latest | high_press | 100 | 32% (24%–42%) |
| keep_15 | our_forwards_slow | main_latest | low_block_counter | 100 | 33% (25%–43%) |
| keep_15 | our_forwards_slow | main_latest | mid_block | 100 | 33% (25%–43%) |
| keep_15 | our_forwards_slow | main_latest | possession | 100 | 33% (25%–43%) |
| keep_15 | our_forwards_slow | main_latest | wing_play | 100 | 33% (25%–43%) |
| keep_15 | our_forwards_slow | selector_latest | chaotic | 100 | 43% (34%–53%) |
| keep_15 | our_forwards_slow | selector_latest | direct | 100 | 43% (34%–53%) |
| keep_15 | our_forwards_slow | selector_latest | high_press | 100 | 43% (34%–53%) |
| keep_15 | our_forwards_slow | selector_latest | low_block_counter | 100 | 43% (34%–53%) |
| keep_15 | our_forwards_slow | selector_latest | mid_block | 100 | 43% (34%–53%) |
| keep_15 | our_forwards_slow | selector_latest | possession | 100 | 43% (34%–53%) |
| keep_15 | our_forwards_slow | selector_latest | wing_play | 100 | 43% (34%–53%) |
| keep_15 | their_defence_tiring | library | chaotic | 100 | 26% (18%–35%) |
| keep_15 | their_defence_tiring | library | direct | 100 | 26% (18%–35%) |
| keep_15 | their_defence_tiring | library | high_press | 100 | 26% (18%–35%) |
| keep_15 | their_defence_tiring | library | low_block_counter | 100 | 26% (18%–35%) |
| keep_15 | their_defence_tiring | library | mid_block | 100 | 26% (18%–35%) |
| keep_15 | their_defence_tiring | library | possession | 100 | 27% (19%–36%) |
| keep_15 | their_defence_tiring | library | wing_play | 100 | 27% (19%–36%) |
| keep_15 | their_defence_tiring | main_latest | chaotic | 100 | 30% (22%–40%) |
| keep_15 | their_defence_tiring | main_latest | direct | 100 | 30% (22%–40%) |
| keep_15 | their_defence_tiring | main_latest | high_press | 100 | 30% (22%–40%) |
| keep_15 | their_defence_tiring | main_latest | low_block_counter | 100 | 30% (22%–40%) |
| keep_15 | their_defence_tiring | main_latest | mid_block | 100 | 30% (22%–40%) |
| keep_15 | their_defence_tiring | main_latest | possession | 100 | 30% (22%–40%) |
| keep_15 | their_defence_tiring | main_latest | wing_play | 100 | 30% (22%–40%) |
| keep_15 | their_defence_tiring | selector_latest | chaotic | 100 | 37% (28%–47%) |
| keep_15 | their_defence_tiring | selector_latest | direct | 100 | 37% (28%–47%) |
| keep_15 | their_defence_tiring | selector_latest | high_press | 100 | 39% (30%–49%) |
| keep_15 | their_defence_tiring | selector_latest | low_block_counter | 100 | 37% (28%–47%) |
| keep_15 | their_defence_tiring | selector_latest | mid_block | 100 | 37% (28%–47%) |
| keep_15 | their_defence_tiring | selector_latest | possession | 100 | 37% (28%–47%) |
| keep_15 | their_defence_tiring | selector_latest | wing_play | 100 | 37% (28%–47%) |
| shot_60 | our_forwards_slow | library | chaotic | 100 | 56% (46%–65%) |
| shot_60 | our_forwards_slow | library | direct | 100 | 59% (49%–68%) |
| shot_60 | our_forwards_slow | library | high_press | 100 | 64% (54%–73%) |
| shot_60 | our_forwards_slow | library | low_block_counter | 100 | 63% (53%–72%) |
| shot_60 | our_forwards_slow | library | mid_block | 100 | 58% (48%–67%) |
| shot_60 | our_forwards_slow | library | possession | 100 | 53% (43%–62%) |
| shot_60 | our_forwards_slow | library | wing_play | 100 | 59% (49%–68%) |
| shot_60 | our_forwards_slow | main_latest | chaotic | 100 | 66% (56%–75%) |
| shot_60 | our_forwards_slow | main_latest | direct | 100 | 67% (57%–75%) |
| shot_60 | our_forwards_slow | main_latest | high_press | 100 | 69% (59%–77%) |
| shot_60 | our_forwards_slow | main_latest | low_block_counter | 100 | 65% (55%–74%) |
| shot_60 | our_forwards_slow | main_latest | mid_block | 100 | 67% (57%–75%) |
| shot_60 | our_forwards_slow | main_latest | possession | 100 | 64% (54%–73%) |
| shot_60 | our_forwards_slow | main_latest | wing_play | 100 | 67% (57%–75%) |
| shot_60 | our_forwards_slow | selector_latest | chaotic | 100 | 75% (66%–82%) |
| shot_60 | our_forwards_slow | selector_latest | direct | 100 | 78% (69%–85%) |
| shot_60 | our_forwards_slow | selector_latest | high_press | 100 | 81% (72%–87%) |
| shot_60 | our_forwards_slow | selector_latest | low_block_counter | 100 | 76% (67%–83%) |
| shot_60 | our_forwards_slow | selector_latest | mid_block | 100 | 73% (64%–81%) |
| shot_60 | our_forwards_slow | selector_latest | possession | 100 | 67% (57%–75%) |
| shot_60 | our_forwards_slow | selector_latest | wing_play | 100 | 79% (70%–86%) |
| shot_60 | their_defence_tiring | library | chaotic | 100 | 78% (69%–85%) |
| shot_60 | their_defence_tiring | library | direct | 100 | 72% (63%–80%) |
| shot_60 | their_defence_tiring | library | high_press | 100 | 72% (63%–80%) |
| shot_60 | their_defence_tiring | library | low_block_counter | 100 | 71% (61%–79%) |
| shot_60 | their_defence_tiring | library | mid_block | 100 | 68% (58%–76%) |
| shot_60 | their_defence_tiring | library | possession | 100 | 67% (57%–75%) |
| shot_60 | their_defence_tiring | library | wing_play | 100 | 80% (71%–87%) |
| shot_60 | their_defence_tiring | main_latest | chaotic | 100 | 80% (71%–87%) |
| shot_60 | their_defence_tiring | main_latest | direct | 100 | 75% (66%–82%) |
| shot_60 | their_defence_tiring | main_latest | high_press | 100 | 76% (67%–83%) |
| shot_60 | their_defence_tiring | main_latest | low_block_counter | 100 | 75% (66%–82%) |
| shot_60 | their_defence_tiring | main_latest | mid_block | 100 | 78% (69%–85%) |
| shot_60 | their_defence_tiring | main_latest | possession | 100 | 79% (70%–86%) |
| shot_60 | their_defence_tiring | main_latest | wing_play | 100 | 82% (73%–88%) |
| shot_60 | their_defence_tiring | selector_latest | chaotic | 100 | 82% (73%–88%) |
| shot_60 | their_defence_tiring | selector_latest | direct | 100 | 80% (71%–87%) |
| shot_60 | their_defence_tiring | selector_latest | high_press | 100 | 81% (72%–87%) |
| shot_60 | their_defence_tiring | selector_latest | low_block_counter | 100 | 84% (76%–90%) |
| shot_60 | their_defence_tiring | selector_latest | mid_block | 100 | 80% (71%–87%) |
| shot_60 | their_defence_tiring | selector_latest | possession | 100 | 72% (63%–80%) |
| shot_60 | their_defence_tiring | selector_latest | wing_play | 100 | 82% (73%–88%) |
