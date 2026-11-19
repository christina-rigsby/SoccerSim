# Objective success rates

100 fixed situations per objective, against every opponent; 95% Wilson intervals. Headline: the rate against the team's weakest opponent. See soccersim/selfplay/objectives.py.

| Objective | Condition | Team | Overall | Weakest opponent | Beats library against every opponent |
|---|---|---|---|---|---|
| chance_60 | fresh | library | 14% (12%–17%) | 11% (6%–19%) v direct | — |
| chance_60 | fresh | lookahead_fast@objective | 24% (21%–27%) | 21% (14%–30%) v chaotic | yes |
| chance_60 | fresh | main_latest | 18% (15%–21%) | 13% (8%–21%) v direct | yes |
| chance_60 | fresh | selector_latest | 10% (8%–12%) | 8% (4%–15%) v chaotic | no |
| keep_30 | fresh | library | 11% (9%–14%) | 11% (6%–19%) v chaotic | — |
| keep_30 | fresh | lookahead_fast@objective | 51% (47%–55%) | 51% (41%–61%) v chaotic | yes |
| keep_30 | fresh | main_latest | 10% (8%–13%) | 10% (6%–17%) v chaotic | no |
| keep_30 | fresh | selector_latest | 21% (18%–24%) | 20% (13%–29%) v high_press | yes |
| protect_180 | fresh | library | 85% (82%–87%) | 83% (74%–89%) v direct | — |
| protect_180 | fresh | lookahead_fast@objective | 87% (85%–90%) | 86% (78%–91%) v chaotic | no |
| protect_180 | fresh | main_latest | 86% (83%–88%) | 82% (73%–88%) v high_press | no |
| protect_180 | fresh | selector_latest | 86% (84%–89%) | 82% (73%–88%) v high_press | no |
| score_120 | fresh | library | 16% (14%–19%) | 14% (9%–22%) v possession | — |
| score_120 | fresh | lookahead_fast@objective | 11% (9%–14%) | 7% (3%–14%) v chaotic | no |
| score_120 | fresh | main_latest | 25% (22%–28%) | 23% (16%–32%) v low_block_counter | yes |
| score_120 | fresh | selector_latest | 15% (13%–18%) | 13% (8%–21%) v wing_play | no |
| win_back_30 | fresh | library | 87% (84%–89%) | 69% (59%–77%) v possession | — |
| win_back_30 | fresh | lookahead_fast@objective | 86% (83%–88%) | 61% (51%–70%) v possession | no |
| win_back_30 | fresh | main_latest | 86% (83%–88%) | 66% (56%–75%) v possession | no |
| win_back_30 | fresh | selector_latest | 85% (82%–87%) | 62% (52%–71%) v possession | no |

## Every pairing

| Objective | Condition | Team | Opponent | n | Rate (95%) |
|---|---|---|---|---|---|
| chance_60 | fresh | library | chaotic | 100 | 15% (9%–23%) |
| chance_60 | fresh | library | direct | 100 | 11% (6%–19%) |
| chance_60 | fresh | library | high_press | 100 | 15% (9%–23%) |
| chance_60 | fresh | library | low_block_counter | 100 | 11% (6%–19%) |
| chance_60 | fresh | library | mid_block | 100 | 12% (7%–20%) |
| chance_60 | fresh | library | possession | 100 | 18% (12%–27%) |
| chance_60 | fresh | library | wing_play | 100 | 16% (10%–24%) |
| chance_60 | fresh | lookahead_fast@objective | chaotic | 100 | 21% (14%–30%) |
| chance_60 | fresh | lookahead_fast@objective | direct | 100 | 23% (16%–32%) |
| chance_60 | fresh | lookahead_fast@objective | high_press | 100 | 26% (18%–35%) |
| chance_60 | fresh | lookahead_fast@objective | low_block_counter | 100 | 22% (15%–31%) |
| chance_60 | fresh | lookahead_fast@objective | mid_block | 100 | 24% (17%–33%) |
| chance_60 | fresh | lookahead_fast@objective | possession | 100 | 22% (15%–31%) |
| chance_60 | fresh | lookahead_fast@objective | wing_play | 100 | 27% (19%–36%) |
| chance_60 | fresh | main_latest | chaotic | 100 | 17% (11%–26%) |
| chance_60 | fresh | main_latest | direct | 100 | 13% (8%–21%) |
| chance_60 | fresh | main_latest | high_press | 100 | 21% (14%–30%) |
| chance_60 | fresh | main_latest | low_block_counter | 100 | 14% (9%–22%) |
| chance_60 | fresh | main_latest | mid_block | 100 | 22% (15%–31%) |
| chance_60 | fresh | main_latest | possession | 100 | 20% (13%–29%) |
| chance_60 | fresh | main_latest | wing_play | 100 | 18% (12%–27%) |
| chance_60 | fresh | selector_latest | chaotic | 100 | 8% (4%–15%) |
| chance_60 | fresh | selector_latest | direct | 100 | 8% (4%–15%) |
| chance_60 | fresh | selector_latest | high_press | 100 | 14% (9%–22%) |
| chance_60 | fresh | selector_latest | low_block_counter | 100 | 9% (5%–16%) |
| chance_60 | fresh | selector_latest | mid_block | 100 | 12% (7%–20%) |
| chance_60 | fresh | selector_latest | possession | 100 | 8% (4%–15%) |
| chance_60 | fresh | selector_latest | wing_play | 100 | 11% (6%–19%) |
| keep_30 | fresh | library | chaotic | 100 | 11% (6%–19%) |
| keep_30 | fresh | library | direct | 100 | 12% (7%–20%) |
| keep_30 | fresh | library | high_press | 100 | 11% (6%–19%) |
| keep_30 | fresh | library | low_block_counter | 100 | 11% (6%–19%) |
| keep_30 | fresh | library | mid_block | 100 | 11% (6%–19%) |
| keep_30 | fresh | library | possession | 100 | 11% (6%–19%) |
| keep_30 | fresh | library | wing_play | 100 | 11% (6%–19%) |
| keep_30 | fresh | lookahead_fast@objective | chaotic | 100 | 51% (41%–61%) |
| keep_30 | fresh | lookahead_fast@objective | direct | 100 | 52% (42%–62%) |
| keep_30 | fresh | lookahead_fast@objective | high_press | 100 | 51% (41%–61%) |
| keep_30 | fresh | lookahead_fast@objective | low_block_counter | 100 | 51% (41%–61%) |
| keep_30 | fresh | lookahead_fast@objective | mid_block | 100 | 51% (41%–61%) |
| keep_30 | fresh | lookahead_fast@objective | possession | 100 | 51% (41%–61%) |
| keep_30 | fresh | lookahead_fast@objective | wing_play | 100 | 51% (41%–61%) |
| keep_30 | fresh | main_latest | chaotic | 100 | 10% (6%–17%) |
| keep_30 | fresh | main_latest | direct | 100 | 10% (6%–17%) |
| keep_30 | fresh | main_latest | high_press | 100 | 11% (6%–19%) |
| keep_30 | fresh | main_latest | low_block_counter | 100 | 10% (6%–17%) |
| keep_30 | fresh | main_latest | mid_block | 100 | 10% (6%–17%) |
| keep_30 | fresh | main_latest | possession | 100 | 10% (6%–17%) |
| keep_30 | fresh | main_latest | wing_play | 100 | 10% (6%–17%) |
| keep_30 | fresh | selector_latest | chaotic | 100 | 21% (14%–30%) |
| keep_30 | fresh | selector_latest | direct | 100 | 21% (14%–30%) |
| keep_30 | fresh | selector_latest | high_press | 100 | 20% (13%–29%) |
| keep_30 | fresh | selector_latest | low_block_counter | 100 | 21% (14%–30%) |
| keep_30 | fresh | selector_latest | mid_block | 100 | 21% (14%–30%) |
| keep_30 | fresh | selector_latest | possession | 100 | 21% (14%–30%) |
| keep_30 | fresh | selector_latest | wing_play | 100 | 21% (14%–30%) |
| protect_180 | fresh | library | chaotic | 100 | 86% (78%–91%) |
| protect_180 | fresh | library | direct | 100 | 83% (74%–89%) |
| protect_180 | fresh | library | high_press | 100 | 83% (74%–89%) |
| protect_180 | fresh | library | low_block_counter | 100 | 87% (79%–92%) |
| protect_180 | fresh | library | mid_block | 100 | 86% (78%–91%) |
| protect_180 | fresh | library | possession | 100 | 85% (77%–91%) |
| protect_180 | fresh | library | wing_play | 100 | 84% (76%–90%) |
| protect_180 | fresh | lookahead_fast@objective | chaotic | 100 | 86% (78%–91%) |
| protect_180 | fresh | lookahead_fast@objective | direct | 100 | 89% (81%–94%) |
| protect_180 | fresh | lookahead_fast@objective | high_press | 100 | 86% (78%–91%) |
| protect_180 | fresh | lookahead_fast@objective | low_block_counter | 100 | 86% (78%–91%) |
| protect_180 | fresh | lookahead_fast@objective | mid_block | 100 | 89% (81%–94%) |
| protect_180 | fresh | lookahead_fast@objective | possession | 100 | 87% (79%–92%) |
| protect_180 | fresh | lookahead_fast@objective | wing_play | 100 | 89% (81%–94%) |
| protect_180 | fresh | main_latest | chaotic | 100 | 89% (81%–94%) |
| protect_180 | fresh | main_latest | direct | 100 | 87% (79%–92%) |
| protect_180 | fresh | main_latest | high_press | 100 | 82% (73%–88%) |
| protect_180 | fresh | main_latest | low_block_counter | 100 | 82% (73%–88%) |
| protect_180 | fresh | main_latest | mid_block | 100 | 87% (79%–92%) |
| protect_180 | fresh | main_latest | possession | 100 | 90% (83%–94%) |
| protect_180 | fresh | main_latest | wing_play | 100 | 85% (77%–91%) |
| protect_180 | fresh | selector_latest | chaotic | 100 | 88% (80%–93%) |
| protect_180 | fresh | selector_latest | direct | 100 | 87% (79%–92%) |
| protect_180 | fresh | selector_latest | high_press | 100 | 82% (73%–88%) |
| protect_180 | fresh | selector_latest | low_block_counter | 100 | 85% (77%–91%) |
| protect_180 | fresh | selector_latest | mid_block | 100 | 84% (76%–90%) |
| protect_180 | fresh | selector_latest | possession | 100 | 90% (83%–94%) |
| protect_180 | fresh | selector_latest | wing_play | 100 | 88% (80%–93%) |
| score_120 | fresh | library | chaotic | 100 | 15% (9%–23%) |
| score_120 | fresh | library | direct | 100 | 15% (9%–23%) |
| score_120 | fresh | library | high_press | 100 | 20% (13%–29%) |
| score_120 | fresh | library | low_block_counter | 100 | 15% (9%–23%) |
| score_120 | fresh | library | mid_block | 100 | 18% (12%–27%) |
| score_120 | fresh | library | possession | 100 | 14% (9%–22%) |
| score_120 | fresh | library | wing_play | 100 | 16% (10%–24%) |
| score_120 | fresh | lookahead_fast@objective | chaotic | 100 | 7% (3%–14%) |
| score_120 | fresh | lookahead_fast@objective | direct | 100 | 11% (6%–19%) |
| score_120 | fresh | lookahead_fast@objective | high_press | 100 | 18% (12%–27%) |
| score_120 | fresh | lookahead_fast@objective | low_block_counter | 100 | 11% (6%–19%) |
| score_120 | fresh | lookahead_fast@objective | mid_block | 100 | 10% (6%–17%) |
| score_120 | fresh | lookahead_fast@objective | possession | 100 | 13% (8%–21%) |
| score_120 | fresh | lookahead_fast@objective | wing_play | 100 | 10% (6%–17%) |
| score_120 | fresh | main_latest | chaotic | 100 | 24% (17%–33%) |
| score_120 | fresh | main_latest | direct | 100 | 26% (18%–35%) |
| score_120 | fresh | main_latest | high_press | 100 | 24% (17%–33%) |
| score_120 | fresh | main_latest | low_block_counter | 100 | 23% (16%–32%) |
| score_120 | fresh | main_latest | mid_block | 100 | 26% (18%–35%) |
| score_120 | fresh | main_latest | possession | 100 | 25% (18%–34%) |
| score_120 | fresh | main_latest | wing_play | 100 | 26% (18%–35%) |
| score_120 | fresh | selector_latest | chaotic | 100 | 15% (9%–23%) |
| score_120 | fresh | selector_latest | direct | 100 | 15% (9%–23%) |
| score_120 | fresh | selector_latest | high_press | 100 | 17% (11%–26%) |
| score_120 | fresh | selector_latest | low_block_counter | 100 | 15% (9%–23%) |
| score_120 | fresh | selector_latest | mid_block | 100 | 19% (13%–28%) |
| score_120 | fresh | selector_latest | possession | 100 | 14% (9%–22%) |
| score_120 | fresh | selector_latest | wing_play | 100 | 13% (8%–21%) |
| win_back_30 | fresh | library | chaotic | 100 | 89% (81%–94%) |
| win_back_30 | fresh | library | direct | 100 | 96% (90%–98%) |
| win_back_30 | fresh | library | high_press | 100 | 97% (92%–99%) |
| win_back_30 | fresh | library | low_block_counter | 100 | 96% (90%–98%) |
| win_back_30 | fresh | library | mid_block | 100 | 75% (66%–82%) |
| win_back_30 | fresh | library | possession | 100 | 69% (59%–77%) |
| win_back_30 | fresh | library | wing_play | 100 | 85% (77%–91%) |
| win_back_30 | fresh | lookahead_fast@objective | chaotic | 100 | 91% (84%–95%) |
| win_back_30 | fresh | lookahead_fast@objective | direct | 100 | 94% (88%–97%) |
| win_back_30 | fresh | lookahead_fast@objective | high_press | 100 | 96% (90%–98%) |
| win_back_30 | fresh | lookahead_fast@objective | low_block_counter | 100 | 94% (88%–97%) |
| win_back_30 | fresh | lookahead_fast@objective | mid_block | 100 | 75% (66%–82%) |
| win_back_30 | fresh | lookahead_fast@objective | possession | 100 | 61% (51%–70%) |
| win_back_30 | fresh | lookahead_fast@objective | wing_play | 100 | 88% (80%–93%) |
| win_back_30 | fresh | main_latest | chaotic | 100 | 88% (80%–93%) |
| win_back_30 | fresh | main_latest | direct | 100 | 95% (89%–98%) |
| win_back_30 | fresh | main_latest | high_press | 100 | 96% (90%–98%) |
| win_back_30 | fresh | main_latest | low_block_counter | 100 | 94% (88%–97%) |
| win_back_30 | fresh | main_latest | mid_block | 100 | 74% (65%–82%) |
| win_back_30 | fresh | main_latest | possession | 100 | 66% (56%–75%) |
| win_back_30 | fresh | main_latest | wing_play | 100 | 86% (78%–91%) |
| win_back_30 | fresh | selector_latest | chaotic | 100 | 91% (84%–95%) |
| win_back_30 | fresh | selector_latest | direct | 100 | 93% (86%–97%) |
| win_back_30 | fresh | selector_latest | high_press | 100 | 94% (88%–97%) |
| win_back_30 | fresh | selector_latest | low_block_counter | 100 | 93% (86%–97%) |
| win_back_30 | fresh | selector_latest | mid_block | 100 | 73% (64%–81%) |
| win_back_30 | fresh | selector_latest | possession | 100 | 62% (52%–71%) |
| win_back_30 | fresh | selector_latest | wing_play | 100 | 87% (79%–92%) |
