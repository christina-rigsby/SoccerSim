# Objective success rates

100 fixed situations per objective, against every opponent; 95% Wilson intervals. Headline: the rate against the team's weakest opponent. See soccersim/selfplay/objectives.py.

| Objective | Condition | Team | Overall | Weakest opponent | Beats library against every opponent | Target (weakest) | Met |
|---|---|---|---|---|---|---|---|
| keep_15 | fresh | expert0@objective | 79% (76%–82%) | 79% (70%–86%) v chaotic | yes | 75% | yes |
| keep_15 | fresh | expert@objective | 77% (74%–80%) | 77% (68%–84%) v chaotic | yes | 75% | yes |
| keep_15 | fresh | library | 27% (24%–30%) | 26% (18%–35%) v chaotic | — | 75% | — |
| shot_60 | fresh | expert0@objective | 82% (79%–85%) | 73% (64%–81%) v mid_block | yes | 90% | no |
| shot_60 | fresh | expert@objective | 71% (67%–74%) | 64% (54%–73%) v mid_block | no | 90% | no |
| shot_60 | fresh | library | 66% (63%–70%) | 63% (53%–72%) v direct | — | 90% | — |
| win_back_20 | fresh | expert0@objective | 79% (76%–82%) | 69% (59%–77%) v mid_block | no | 75% | no |
| win_back_20 | fresh | expert@objective | 80% (76%–82%) | 69% (59%–77%) v mid_block | no | 75% | no |
| win_back_20 | fresh | library | 78% (75%–81%) | 68% (58%–76%) v possession | — | 75% | — |

## Every pairing

| Objective | Condition | Team | Opponent | n | Rate (95%) |
|---|---|---|---|---|---|
| keep_15 | fresh | expert0@objective | chaotic | 100 | 79% (70%–86%) |
| keep_15 | fresh | expert0@objective | direct | 100 | 79% (70%–86%) |
| keep_15 | fresh | expert0@objective | high_press | 100 | 79% (70%–86%) |
| keep_15 | fresh | expert0@objective | low_block_counter | 100 | 79% (70%–86%) |
| keep_15 | fresh | expert0@objective | mid_block | 100 | 79% (70%–86%) |
| keep_15 | fresh | expert0@objective | possession | 100 | 80% (71%–87%) |
| keep_15 | fresh | expert0@objective | wing_play | 100 | 80% (71%–87%) |
| keep_15 | fresh | expert@objective | chaotic | 100 | 77% (68%–84%) |
| keep_15 | fresh | expert@objective | direct | 100 | 77% (68%–84%) |
| keep_15 | fresh | expert@objective | high_press | 100 | 79% (70%–86%) |
| keep_15 | fresh | expert@objective | low_block_counter | 100 | 77% (68%–84%) |
| keep_15 | fresh | expert@objective | mid_block | 100 | 77% (68%–84%) |
| keep_15 | fresh | expert@objective | possession | 100 | 77% (68%–84%) |
| keep_15 | fresh | expert@objective | wing_play | 100 | 77% (68%–84%) |
| keep_15 | fresh | library | chaotic | 100 | 26% (18%–35%) |
| keep_15 | fresh | library | direct | 100 | 27% (19%–36%) |
| keep_15 | fresh | library | high_press | 100 | 26% (18%–35%) |
| keep_15 | fresh | library | low_block_counter | 100 | 27% (19%–36%) |
| keep_15 | fresh | library | mid_block | 100 | 27% (19%–36%) |
| keep_15 | fresh | library | possession | 100 | 27% (19%–36%) |
| keep_15 | fresh | library | wing_play | 100 | 27% (19%–36%) |
| shot_60 | fresh | expert0@objective | chaotic | 100 | 83% (74%–89%) |
| shot_60 | fresh | expert0@objective | direct | 100 | 87% (79%–92%) |
| shot_60 | fresh | expert0@objective | high_press | 100 | 89% (81%–94%) |
| shot_60 | fresh | expert0@objective | low_block_counter | 100 | 87% (79%–92%) |
| shot_60 | fresh | expert0@objective | mid_block | 100 | 73% (64%–81%) |
| shot_60 | fresh | expert0@objective | possession | 100 | 75% (66%–82%) |
| shot_60 | fresh | expert0@objective | wing_play | 100 | 80% (71%–87%) |
| shot_60 | fresh | expert@objective | chaotic | 100 | 77% (68%–84%) |
| shot_60 | fresh | expert@objective | direct | 100 | 75% (66%–82%) |
| shot_60 | fresh | expert@objective | high_press | 100 | 71% (61%–79%) |
| shot_60 | fresh | expert@objective | low_block_counter | 100 | 77% (68%–84%) |
| shot_60 | fresh | expert@objective | mid_block | 100 | 64% (54%–73%) |
| shot_60 | fresh | expert@objective | possession | 100 | 67% (57%–75%) |
| shot_60 | fresh | expert@objective | wing_play | 100 | 64% (54%–73%) |
| shot_60 | fresh | library | chaotic | 100 | 68% (58%–76%) |
| shot_60 | fresh | library | direct | 100 | 63% (53%–72%) |
| shot_60 | fresh | library | high_press | 100 | 64% (54%–73%) |
| shot_60 | fresh | library | low_block_counter | 100 | 63% (53%–72%) |
| shot_60 | fresh | library | mid_block | 100 | 68% (58%–76%) |
| shot_60 | fresh | library | possession | 100 | 67% (57%–75%) |
| shot_60 | fresh | library | wing_play | 100 | 71% (61%–79%) |
| win_back_20 | fresh | expert0@objective | chaotic | 100 | 83% (74%–89%) |
| win_back_20 | fresh | expert0@objective | direct | 100 | 85% (77%–91%) |
| win_back_20 | fresh | expert0@objective | high_press | 100 | 83% (74%–89%) |
| win_back_20 | fresh | expert0@objective | low_block_counter | 100 | 83% (74%–89%) |
| win_back_20 | fresh | expert0@objective | mid_block | 100 | 69% (59%–77%) |
| win_back_20 | fresh | expert0@objective | possession | 100 | 70% (60%–78%) |
| win_back_20 | fresh | expert0@objective | wing_play | 100 | 80% (71%–87%) |
| win_back_20 | fresh | expert@objective | chaotic | 100 | 82% (73%–88%) |
| win_back_20 | fresh | expert@objective | direct | 100 | 86% (78%–91%) |
| win_back_20 | fresh | expert@objective | high_press | 100 | 84% (76%–90%) |
| win_back_20 | fresh | expert@objective | low_block_counter | 100 | 84% (76%–90%) |
| win_back_20 | fresh | expert@objective | mid_block | 100 | 69% (59%–77%) |
| win_back_20 | fresh | expert@objective | possession | 100 | 71% (61%–79%) |
| win_back_20 | fresh | expert@objective | wing_play | 100 | 81% (72%–87%) |
| win_back_20 | fresh | library | chaotic | 100 | 82% (73%–88%) |
| win_back_20 | fresh | library | direct | 100 | 85% (77%–91%) |
| win_back_20 | fresh | library | high_press | 100 | 83% (74%–89%) |
| win_back_20 | fresh | library | low_block_counter | 100 | 83% (74%–89%) |
| win_back_20 | fresh | library | mid_block | 100 | 70% (60%–78%) |
| win_back_20 | fresh | library | possession | 100 | 68% (58%–76%) |
| win_back_20 | fresh | library | wing_play | 100 | 78% (69%–85%) |
