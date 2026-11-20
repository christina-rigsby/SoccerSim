# Objective success rates

50 fixed situations per objective, against every opponent; 95% Wilson intervals. Headline: the rate against the team's weakest opponent. See soccersim/selfplay/objectives.py.

| Objective | Condition | Team | Overall | Weakest opponent | Beats library against every opponent | Target (weakest) | Met |
|---|---|---|---|---|---|---|---|
| chance_180 | fresh | library | 41% (36%–46%) | 26% (16%–40%) v high_press | — | 60% | — |
| chance_180 | fresh | main_latest | 50% (45%–55%) | 40% (28%–54%) v low_block_counter | no | 60% | no |
| chance_180 | fresh | selector_latest | 46% (41%–52%) | 34% (22%–48%) v chaotic | no | 60% | no |
| protect_300 | fresh | library | 75% (71%–80%) | 70% (56%–81%) v direct | — | 90% | — |
| protect_300 | fresh | main_latest | 73% (69%–78%) | 64% (50%–76%) v high_press | no | 90% | no |
| protect_300 | fresh | selector_latest | 69% (64%–73%) | 56% (42%–69%) v high_press | no | 90% | no |
| score_180 | fresh | library | 22% (18%–26%) | 14% (7%–26%) v chaotic | — | — | — |
| score_180 | fresh | main_latest | 26% (22%–31%) | 16% (8%–29%) v direct | no | — | — |
| score_180 | fresh | selector_latest | 26% (22%–31%) | 22% (13%–35%) v direct | yes | — | — |

## Every pairing

| Objective | Condition | Team | Opponent | n | Rate (95%) |
|---|---|---|---|---|---|
| chance_180 | fresh | library | chaotic | 50 | 40% (28%–54%) |
| chance_180 | fresh | library | direct | 50 | 34% (22%–48%) |
| chance_180 | fresh | library | high_press | 50 | 26% (16%–40%) |
| chance_180 | fresh | library | low_block_counter | 50 | 40% (28%–54%) |
| chance_180 | fresh | library | mid_block | 50 | 46% (33%–60%) |
| chance_180 | fresh | library | possession | 50 | 60% (46%–72%) |
| chance_180 | fresh | library | wing_play | 50 | 42% (29%–56%) |
| chance_180 | fresh | main_latest | chaotic | 50 | 58% (44%–71%) |
| chance_180 | fresh | main_latest | direct | 50 | 42% (29%–56%) |
| chance_180 | fresh | main_latest | high_press | 50 | 44% (31%–58%) |
| chance_180 | fresh | main_latest | low_block_counter | 50 | 40% (28%–54%) |
| chance_180 | fresh | main_latest | mid_block | 50 | 50% (37%–63%) |
| chance_180 | fresh | main_latest | possession | 50 | 68% (54%–79%) |
| chance_180 | fresh | main_latest | wing_play | 50 | 50% (37%–63%) |
| chance_180 | fresh | selector_latest | chaotic | 50 | 34% (22%–48%) |
| chance_180 | fresh | selector_latest | direct | 50 | 42% (29%–56%) |
| chance_180 | fresh | selector_latest | high_press | 50 | 42% (29%–56%) |
| chance_180 | fresh | selector_latest | low_block_counter | 50 | 44% (31%–58%) |
| chance_180 | fresh | selector_latest | mid_block | 50 | 52% (39%–65%) |
| chance_180 | fresh | selector_latest | possession | 50 | 64% (50%–76%) |
| chance_180 | fresh | selector_latest | wing_play | 50 | 46% (33%–60%) |
| protect_300 | fresh | library | chaotic | 50 | 74% (60%–84%) |
| protect_300 | fresh | library | direct | 50 | 70% (56%–81%) |
| protect_300 | fresh | library | high_press | 50 | 74% (60%–84%) |
| protect_300 | fresh | library | low_block_counter | 50 | 70% (56%–81%) |
| protect_300 | fresh | library | mid_block | 50 | 82% (69%–90%) |
| protect_300 | fresh | library | possession | 50 | 82% (69%–90%) |
| protect_300 | fresh | library | wing_play | 50 | 76% (63%–86%) |
| protect_300 | fresh | main_latest | chaotic | 50 | 66% (52%–78%) |
| protect_300 | fresh | main_latest | direct | 50 | 78% (65%–87%) |
| protect_300 | fresh | main_latest | high_press | 50 | 64% (50%–76%) |
| protect_300 | fresh | main_latest | low_block_counter | 50 | 72% (58%–83%) |
| protect_300 | fresh | main_latest | mid_block | 50 | 80% (67%–89%) |
| protect_300 | fresh | main_latest | possession | 50 | 70% (56%–81%) |
| protect_300 | fresh | main_latest | wing_play | 50 | 84% (71%–92%) |
| protect_300 | fresh | selector_latest | chaotic | 50 | 72% (58%–83%) |
| protect_300 | fresh | selector_latest | direct | 50 | 64% (50%–76%) |
| protect_300 | fresh | selector_latest | high_press | 50 | 56% (42%–69%) |
| protect_300 | fresh | selector_latest | low_block_counter | 50 | 64% (50%–76%) |
| protect_300 | fresh | selector_latest | mid_block | 50 | 78% (65%–87%) |
| protect_300 | fresh | selector_latest | possession | 50 | 78% (65%–87%) |
| protect_300 | fresh | selector_latest | wing_play | 50 | 68% (54%–79%) |
| score_180 | fresh | library | chaotic | 50 | 14% (7%–26%) |
| score_180 | fresh | library | direct | 50 | 20% (11%–33%) |
| score_180 | fresh | library | high_press | 50 | 22% (13%–35%) |
| score_180 | fresh | library | low_block_counter | 50 | 22% (13%–35%) |
| score_180 | fresh | library | mid_block | 50 | 22% (13%–35%) |
| score_180 | fresh | library | possession | 50 | 30% (19%–44%) |
| score_180 | fresh | library | wing_play | 50 | 22% (13%–35%) |
| score_180 | fresh | main_latest | chaotic | 50 | 28% (17%–42%) |
| score_180 | fresh | main_latest | direct | 50 | 16% (8%–29%) |
| score_180 | fresh | main_latest | high_press | 50 | 24% (14%–37%) |
| score_180 | fresh | main_latest | low_block_counter | 50 | 20% (11%–33%) |
| score_180 | fresh | main_latest | mid_block | 50 | 30% (19%–44%) |
| score_180 | fresh | main_latest | possession | 50 | 32% (21%–46%) |
| score_180 | fresh | main_latest | wing_play | 50 | 32% (21%–46%) |
| score_180 | fresh | selector_latest | chaotic | 50 | 26% (16%–40%) |
| score_180 | fresh | selector_latest | direct | 50 | 22% (13%–35%) |
| score_180 | fresh | selector_latest | high_press | 50 | 26% (16%–40%) |
| score_180 | fresh | selector_latest | low_block_counter | 50 | 24% (14%–37%) |
| score_180 | fresh | selector_latest | mid_block | 50 | 26% (16%–40%) |
| score_180 | fresh | selector_latest | possession | 50 | 32% (21%–46%) |
| score_180 | fresh | selector_latest | wing_play | 50 | 26% (16%–40%) |
