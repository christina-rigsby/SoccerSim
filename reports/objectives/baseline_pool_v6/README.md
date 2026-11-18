# Objective success rates

200 fixed situations per objective, against every opponent; 95% Wilson intervals. Headline: the rate against the team's weakest opponent. See soccersim/selfplay/objectives.py.

| Objective | Condition | Team | Overall | Weakest opponent | Beats library against every opponent |
|---|---|---|---|---|---|
| chance_30 | fresh | library | 24% (22%–27%) | 22% (17%–29%) v direct | — |
| chance_30 | fresh | lookahead_fast@objective | 39% (36%–41%) | 36% (30%–43%) v direct | yes |
| chance_30 | fresh | selector_latest | 20% (18%–22%) | 18% (13%–23%) v direct | no |
| keep_30 | fresh | library | 19% (17%–21%) | 17% (12%–23%) v high_press | — |
| keep_30 | fresh | lookahead_fast@objective | 43% (41%–46%) | 42% (36%–49%) v high_press | yes |
| keep_30 | fresh | selector_latest | 12% (11%–14%) | 12% (8%–17%) v high_press | no |
| protect_60 | fresh | library | 94% (93%–96%) | 93% (89%–96%) v high_press | — |
| protect_60 | fresh | lookahead_fast@objective | 96% (94%–97%) | 95% (91%–97%) v chaotic | no |
| protect_60 | fresh | selector_latest | 95% (94%–96%) | 94% (89%–96%) v chaotic | no |
| score_30 | fresh | library | 5% (4%–6%) | 4% (2%–8%) v direct | — |
| score_30 | fresh | lookahead_fast@objective | 8% (6%–9%) | 6% (3%–10%) v direct | yes |
| score_30 | fresh | selector_latest | 6% (5%–8%) | 4% (2%–8%) v direct | no |
| win_back_8 | fresh | library | 41% (39%–44%) | 24% (19%–31%) v possession | — |
| win_back_8 | fresh | lookahead_fast@objective | 45% (43%–48%) | 28% (23%–35%) v possession | yes |
| win_back_8 | fresh | selector_latest | 43% (41%–46%) | 26% (20%–32%) v possession | yes |

## Every pairing

| Objective | Condition | Team | Opponent | n | Rate (95%) |
|---|---|---|---|---|---|
| chance_30 | fresh | library | chaotic | 200 | 24% (19%–31%) |
| chance_30 | fresh | library | direct | 200 | 22% (17%–29%) |
| chance_30 | fresh | library | high_press | 200 | 27% (21%–34%) |
| chance_30 | fresh | library | low_block_counter | 200 | 22% (17%–29%) |
| chance_30 | fresh | library | mid_block | 200 | 24% (18%–30%) |
| chance_30 | fresh | library | possession | 200 | 26% (20%–32%) |
| chance_30 | fresh | library | wing_play | 200 | 24% (19%–31%) |
| chance_30 | fresh | lookahead_fast@objective | chaotic | 200 | 37% (31%–44%) |
| chance_30 | fresh | lookahead_fast@objective | direct | 200 | 36% (30%–43%) |
| chance_30 | fresh | lookahead_fast@objective | high_press | 200 | 41% (34%–48%) |
| chance_30 | fresh | lookahead_fast@objective | low_block_counter | 200 | 37% (31%–44%) |
| chance_30 | fresh | lookahead_fast@objective | mid_block | 200 | 39% (33%–46%) |
| chance_30 | fresh | lookahead_fast@objective | possession | 200 | 42% (35%–49%) |
| chance_30 | fresh | lookahead_fast@objective | wing_play | 200 | 40% (33%–46%) |
| chance_30 | fresh | selector_latest | chaotic | 200 | 20% (15%–27%) |
| chance_30 | fresh | selector_latest | direct | 200 | 18% (13%–23%) |
| chance_30 | fresh | selector_latest | high_press | 200 | 22% (16%–28%) |
| chance_30 | fresh | selector_latest | low_block_counter | 200 | 18% (13%–24%) |
| chance_30 | fresh | selector_latest | mid_block | 200 | 21% (16%–27%) |
| chance_30 | fresh | selector_latest | possession | 200 | 22% (17%–28%) |
| chance_30 | fresh | selector_latest | wing_play | 200 | 20% (15%–27%) |
| keep_30 | fresh | library | chaotic | 200 | 18% (14%–24%) |
| keep_30 | fresh | library | direct | 200 | 20% (15%–26%) |
| keep_30 | fresh | library | high_press | 200 | 17% (12%–23%) |
| keep_30 | fresh | library | low_block_counter | 200 | 20% (15%–26%) |
| keep_30 | fresh | library | mid_block | 200 | 20% (15%–26%) |
| keep_30 | fresh | library | possession | 200 | 18% (14%–24%) |
| keep_30 | fresh | library | wing_play | 200 | 18% (14%–24%) |
| keep_30 | fresh | lookahead_fast@objective | chaotic | 200 | 43% (36%–50%) |
| keep_30 | fresh | lookahead_fast@objective | direct | 200 | 44% (37%–50%) |
| keep_30 | fresh | lookahead_fast@objective | high_press | 200 | 42% (36%–49%) |
| keep_30 | fresh | lookahead_fast@objective | low_block_counter | 200 | 44% (37%–51%) |
| keep_30 | fresh | lookahead_fast@objective | mid_block | 200 | 44% (37%–51%) |
| keep_30 | fresh | lookahead_fast@objective | possession | 200 | 43% (36%–50%) |
| keep_30 | fresh | lookahead_fast@objective | wing_play | 200 | 43% (36%–50%) |
| keep_30 | fresh | selector_latest | chaotic | 200 | 12% (9%–18%) |
| keep_30 | fresh | selector_latest | direct | 200 | 12% (9%–18%) |
| keep_30 | fresh | selector_latest | high_press | 200 | 12% (8%–17%) |
| keep_30 | fresh | selector_latest | low_block_counter | 200 | 12% (9%–18%) |
| keep_30 | fresh | selector_latest | mid_block | 200 | 12% (9%–18%) |
| keep_30 | fresh | selector_latest | possession | 200 | 12% (9%–18%) |
| keep_30 | fresh | selector_latest | wing_play | 200 | 12% (9%–18%) |
| protect_60 | fresh | library | chaotic | 200 | 94% (90%–97%) |
| protect_60 | fresh | library | direct | 200 | 94% (90%–97%) |
| protect_60 | fresh | library | high_press | 200 | 93% (89%–96%) |
| protect_60 | fresh | library | low_block_counter | 200 | 93% (89%–96%) |
| protect_60 | fresh | library | mid_block | 200 | 97% (94%–99%) |
| protect_60 | fresh | library | possession | 200 | 96% (92%–98%) |
| protect_60 | fresh | library | wing_play | 200 | 94% (89%–96%) |
| protect_60 | fresh | lookahead_fast@objective | chaotic | 200 | 95% (91%–97%) |
| protect_60 | fresh | lookahead_fast@objective | direct | 200 | 96% (92%–98%) |
| protect_60 | fresh | lookahead_fast@objective | high_press | 200 | 95% (91%–97%) |
| protect_60 | fresh | lookahead_fast@objective | low_block_counter | 200 | 96% (92%–98%) |
| protect_60 | fresh | lookahead_fast@objective | mid_block | 200 | 96% (92%–98%) |
| protect_60 | fresh | lookahead_fast@objective | possession | 200 | 97% (94%–99%) |
| protect_60 | fresh | lookahead_fast@objective | wing_play | 200 | 96% (92%–98%) |
| protect_60 | fresh | selector_latest | chaotic | 200 | 94% (89%–96%) |
| protect_60 | fresh | selector_latest | direct | 200 | 95% (91%–97%) |
| protect_60 | fresh | selector_latest | high_press | 200 | 94% (90%–97%) |
| protect_60 | fresh | selector_latest | low_block_counter | 200 | 95% (91%–97%) |
| protect_60 | fresh | selector_latest | mid_block | 200 | 96% (92%–98%) |
| protect_60 | fresh | selector_latest | possession | 200 | 96% (92%–98%) |
| protect_60 | fresh | selector_latest | wing_play | 200 | 96% (92%–98%) |
| score_30 | fresh | library | chaotic | 200 | 5% (3%–9%) |
| score_30 | fresh | library | direct | 200 | 4% (2%–8%) |
| score_30 | fresh | library | high_press | 200 | 6% (3%–10%) |
| score_30 | fresh | library | low_block_counter | 200 | 4% (2%–8%) |
| score_30 | fresh | library | mid_block | 200 | 6% (3%–10%) |
| score_30 | fresh | library | possession | 200 | 4% (2%–8%) |
| score_30 | fresh | library | wing_play | 200 | 6% (3%–10%) |
| score_30 | fresh | lookahead_fast@objective | chaotic | 200 | 7% (4%–11%) |
| score_30 | fresh | lookahead_fast@objective | direct | 200 | 6% (3%–10%) |
| score_30 | fresh | lookahead_fast@objective | high_press | 200 | 10% (7%–15%) |
| score_30 | fresh | lookahead_fast@objective | low_block_counter | 200 | 6% (3%–10%) |
| score_30 | fresh | lookahead_fast@objective | mid_block | 200 | 7% (4%–11%) |
| score_30 | fresh | lookahead_fast@objective | possession | 200 | 8% (5%–13%) |
| score_30 | fresh | lookahead_fast@objective | wing_play | 200 | 9% (6%–14%) |
| score_30 | fresh | selector_latest | chaotic | 200 | 8% (5%–12%) |
| score_30 | fresh | selector_latest | direct | 200 | 4% (2%–8%) |
| score_30 | fresh | selector_latest | high_press | 200 | 7% (4%–11%) |
| score_30 | fresh | selector_latest | low_block_counter | 200 | 4% (2%–8%) |
| score_30 | fresh | selector_latest | mid_block | 200 | 7% (4%–11%) |
| score_30 | fresh | selector_latest | possession | 200 | 7% (4%–11%) |
| score_30 | fresh | selector_latest | wing_play | 200 | 7% (4%–11%) |
| win_back_8 | fresh | library | chaotic | 200 | 38% (31%–44%) |
| win_back_8 | fresh | library | direct | 200 | 54% (47%–60%) |
| win_back_8 | fresh | library | high_press | 200 | 54% (47%–61%) |
| win_back_8 | fresh | library | low_block_counter | 200 | 55% (48%–61%) |
| win_back_8 | fresh | library | mid_block | 200 | 28% (22%–35%) |
| win_back_8 | fresh | library | possession | 200 | 24% (19%–31%) |
| win_back_8 | fresh | library | wing_play | 200 | 38% (32%–45%) |
| win_back_8 | fresh | lookahead_fast@objective | chaotic | 200 | 42% (35%–49%) |
| win_back_8 | fresh | lookahead_fast@objective | direct | 200 | 56% (49%–62%) |
| win_back_8 | fresh | lookahead_fast@objective | high_press | 200 | 56% (50%–63%) |
| win_back_8 | fresh | lookahead_fast@objective | low_block_counter | 200 | 57% (50%–64%) |
| win_back_8 | fresh | lookahead_fast@objective | mid_block | 200 | 34% (27%–40%) |
| win_back_8 | fresh | lookahead_fast@objective | possession | 200 | 28% (23%–35%) |
| win_back_8 | fresh | lookahead_fast@objective | wing_play | 200 | 44% (37%–50%) |
| win_back_8 | fresh | selector_latest | chaotic | 200 | 41% (34%–48%) |
| win_back_8 | fresh | selector_latest | direct | 200 | 55% (48%–62%) |
| win_back_8 | fresh | selector_latest | high_press | 200 | 56% (49%–63%) |
| win_back_8 | fresh | selector_latest | low_block_counter | 200 | 56% (50%–63%) |
| win_back_8 | fresh | selector_latest | mid_block | 200 | 30% (25%–37%) |
| win_back_8 | fresh | selector_latest | possession | 200 | 26% (20%–32%) |
| win_back_8 | fresh | selector_latest | wing_play | 200 | 38% (32%–45%) |
