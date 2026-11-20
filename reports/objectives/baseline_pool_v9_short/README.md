# Objective success rates

100 fixed situations per objective, against every opponent; 95% Wilson intervals. Headline: the rate against the team's weakest opponent. See soccersim/selfplay/objectives.py.

| Objective | Condition | Team | Overall | Weakest opponent | Beats library against every opponent | Target (weakest) | Met |
|---|---|---|---|---|---|---|---|
| keep_15 | fresh | library | 27% (24%–30%) | 26% (18%–35%) v chaotic | — | 75% | — |
| keep_15 | fresh | lookahead_fast@objective | 74% (71%–77%) | 72% (63%–80%) v high_press | yes | 75% | no |
| keep_15 | fresh | main_latest | 32% (29%–36%) | 32% (24%–42%) v chaotic | yes | 75% | no |
| keep_15 | fresh | selector_latest | 35% (31%–38%) | 34% (25%–44%) v chaotic | yes | 75% | no |
| shot_60 | fresh | library | 66% (63%–70%) | 63% (53%–72%) v direct | — | 90% | — |
| shot_60 | fresh | lookahead_fast@objective | 83% (80%–85%) | 79% (70%–86%) v high_press | yes | 90% | no |
| shot_60 | fresh | main_latest | 78% (75%–81%) | 77% (68%–84%) v mid_block | yes | 90% | no |
| shot_60 | fresh | selector_latest | 83% (80%–85%) | 80% (71%–87%) v possession | yes | 90% | no |
| win_back_20 | fresh | library | 78% (75%–81%) | 68% (58%–76%) v possession | — | 75% | — |
| win_back_20 | fresh | lookahead_fast@objective | 82% (79%–84%) | 73% (64%–81%) v possession | no | 75% | no |
| win_back_20 | fresh | main_latest | 78% (74%–81%) | 68% (58%–76%) v possession | no | 75% | no |
| win_back_20 | fresh | selector_latest | 78% (75%–81%) | 60% (50%–69%) v possession | no | 75% | no |

## Every pairing

| Objective | Condition | Team | Opponent | n | Rate (95%) |
|---|---|---|---|---|---|
| keep_15 | fresh | library | chaotic | 100 | 26% (18%–35%) |
| keep_15 | fresh | library | direct | 100 | 27% (19%–36%) |
| keep_15 | fresh | library | high_press | 100 | 26% (18%–35%) |
| keep_15 | fresh | library | low_block_counter | 100 | 27% (19%–36%) |
| keep_15 | fresh | library | mid_block | 100 | 27% (19%–36%) |
| keep_15 | fresh | library | possession | 100 | 27% (19%–36%) |
| keep_15 | fresh | library | wing_play | 100 | 27% (19%–36%) |
| keep_15 | fresh | lookahead_fast@objective | chaotic | 100 | 73% (64%–81%) |
| keep_15 | fresh | lookahead_fast@objective | direct | 100 | 75% (66%–82%) |
| keep_15 | fresh | lookahead_fast@objective | high_press | 100 | 72% (63%–80%) |
| keep_15 | fresh | lookahead_fast@objective | low_block_counter | 100 | 75% (66%–82%) |
| keep_15 | fresh | lookahead_fast@objective | mid_block | 100 | 75% (66%–82%) |
| keep_15 | fresh | lookahead_fast@objective | possession | 100 | 74% (65%–82%) |
| keep_15 | fresh | lookahead_fast@objective | wing_play | 100 | 74% (65%–82%) |
| keep_15 | fresh | main_latest | chaotic | 100 | 32% (24%–42%) |
| keep_15 | fresh | main_latest | direct | 100 | 32% (24%–42%) |
| keep_15 | fresh | main_latest | high_press | 100 | 32% (24%–42%) |
| keep_15 | fresh | main_latest | low_block_counter | 100 | 32% (24%–42%) |
| keep_15 | fresh | main_latest | mid_block | 100 | 32% (24%–42%) |
| keep_15 | fresh | main_latest | possession | 100 | 32% (24%–42%) |
| keep_15 | fresh | main_latest | wing_play | 100 | 32% (24%–42%) |
| keep_15 | fresh | selector_latest | chaotic | 100 | 34% (25%–44%) |
| keep_15 | fresh | selector_latest | direct | 100 | 35% (26%–45%) |
| keep_15 | fresh | selector_latest | high_press | 100 | 35% (26%–45%) |
| keep_15 | fresh | selector_latest | low_block_counter | 100 | 35% (26%–45%) |
| keep_15 | fresh | selector_latest | mid_block | 100 | 35% (26%–45%) |
| keep_15 | fresh | selector_latest | possession | 100 | 35% (26%–45%) |
| keep_15 | fresh | selector_latest | wing_play | 100 | 35% (26%–45%) |
| shot_60 | fresh | library | chaotic | 100 | 68% (58%–76%) |
| shot_60 | fresh | library | direct | 100 | 63% (53%–72%) |
| shot_60 | fresh | library | high_press | 100 | 64% (54%–73%) |
| shot_60 | fresh | library | low_block_counter | 100 | 63% (53%–72%) |
| shot_60 | fresh | library | mid_block | 100 | 68% (58%–76%) |
| shot_60 | fresh | library | possession | 100 | 67% (57%–75%) |
| shot_60 | fresh | library | wing_play | 100 | 71% (61%–79%) |
| shot_60 | fresh | lookahead_fast@objective | chaotic | 100 | 90% (83%–94%) |
| shot_60 | fresh | lookahead_fast@objective | direct | 100 | 81% (72%–87%) |
| shot_60 | fresh | lookahead_fast@objective | high_press | 100 | 79% (70%–86%) |
| shot_60 | fresh | lookahead_fast@objective | low_block_counter | 100 | 79% (70%–86%) |
| shot_60 | fresh | lookahead_fast@objective | mid_block | 100 | 83% (74%–89%) |
| shot_60 | fresh | lookahead_fast@objective | possession | 100 | 83% (74%–89%) |
| shot_60 | fresh | lookahead_fast@objective | wing_play | 100 | 83% (74%–89%) |
| shot_60 | fresh | main_latest | chaotic | 100 | 80% (71%–87%) |
| shot_60 | fresh | main_latest | direct | 100 | 78% (69%–85%) |
| shot_60 | fresh | main_latest | high_press | 100 | 80% (71%–87%) |
| shot_60 | fresh | main_latest | low_block_counter | 100 | 78% (69%–85%) |
| shot_60 | fresh | main_latest | mid_block | 100 | 77% (68%–84%) |
| shot_60 | fresh | main_latest | possession | 100 | 77% (68%–84%) |
| shot_60 | fresh | main_latest | wing_play | 100 | 78% (69%–85%) |
| shot_60 | fresh | selector_latest | chaotic | 100 | 83% (74%–89%) |
| shot_60 | fresh | selector_latest | direct | 100 | 82% (73%–88%) |
| shot_60 | fresh | selector_latest | high_press | 100 | 82% (73%–88%) |
| shot_60 | fresh | selector_latest | low_block_counter | 100 | 84% (76%–90%) |
| shot_60 | fresh | selector_latest | mid_block | 100 | 83% (74%–89%) |
| shot_60 | fresh | selector_latest | possession | 100 | 80% (71%–87%) |
| shot_60 | fresh | selector_latest | wing_play | 100 | 85% (77%–91%) |
| win_back_20 | fresh | library | chaotic | 100 | 82% (73%–88%) |
| win_back_20 | fresh | library | direct | 100 | 85% (77%–91%) |
| win_back_20 | fresh | library | high_press | 100 | 83% (74%–89%) |
| win_back_20 | fresh | library | low_block_counter | 100 | 83% (74%–89%) |
| win_back_20 | fresh | library | mid_block | 100 | 70% (60%–78%) |
| win_back_20 | fresh | library | possession | 100 | 68% (58%–76%) |
| win_back_20 | fresh | library | wing_play | 100 | 78% (69%–85%) |
| win_back_20 | fresh | lookahead_fast@objective | chaotic | 100 | 82% (73%–88%) |
| win_back_20 | fresh | lookahead_fast@objective | direct | 100 | 88% (80%–93%) |
| win_back_20 | fresh | lookahead_fast@objective | high_press | 100 | 84% (76%–90%) |
| win_back_20 | fresh | lookahead_fast@objective | low_block_counter | 100 | 85% (77%–91%) |
| win_back_20 | fresh | lookahead_fast@objective | mid_block | 100 | 79% (70%–86%) |
| win_back_20 | fresh | lookahead_fast@objective | possession | 100 | 73% (64%–81%) |
| win_back_20 | fresh | lookahead_fast@objective | wing_play | 100 | 81% (72%–87%) |
| win_back_20 | fresh | main_latest | chaotic | 100 | 81% (72%–87%) |
| win_back_20 | fresh | main_latest | direct | 100 | 83% (74%–89%) |
| win_back_20 | fresh | main_latest | high_press | 100 | 82% (73%–88%) |
| win_back_20 | fresh | main_latest | low_block_counter | 100 | 82% (73%–88%) |
| win_back_20 | fresh | main_latest | mid_block | 100 | 72% (63%–80%) |
| win_back_20 | fresh | main_latest | possession | 100 | 68% (58%–76%) |
| win_back_20 | fresh | main_latest | wing_play | 100 | 75% (66%–82%) |
| win_back_20 | fresh | selector_latest | chaotic | 100 | 82% (73%–88%) |
| win_back_20 | fresh | selector_latest | direct | 100 | 86% (78%–91%) |
| win_back_20 | fresh | selector_latest | high_press | 100 | 84% (76%–90%) |
| win_back_20 | fresh | selector_latest | low_block_counter | 100 | 85% (77%–91%) |
| win_back_20 | fresh | selector_latest | mid_block | 100 | 73% (64%–81%) |
| win_back_20 | fresh | selector_latest | possession | 100 | 60% (50%–69%) |
| win_back_20 | fresh | selector_latest | wing_play | 100 | 77% (68%–84%) |
