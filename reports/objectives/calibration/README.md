# Objective calibration: success rate against the time allowed

20 situations per kind, against every style (high_press, mid_block, low_block_counter, possession, direct, wing_play, chaotic); `python scripts/objective_calibration.py`. Rate overall, and against the weakest style.

| Objective | Within | library | main_latest |
|---|---|---|---|
| score | 30 s | 4% (weakest 0% v direct) | 19% (weakest 15% v chaotic) |
| score | 60 s | 5% (weakest 0% v low_block_counter) | 24% (weakest 15% v direct) |
| score | 120 s | 11% (weakest 5% v high_press) | 26% (weakest 15% v direct) |
| score | 180 s | 16% (weakest 5% v low_block_counter) | 30% (weakest 15% v direct) |
| chance | 30 s | 11% (weakest 10% v direct) | 22% (weakest 20% v chaotic) |
| chance | 60 s | 16% (weakest 10% v mid_block) | 31% (weakest 20% v possession) |
| chance | 120 s | 24% (weakest 20% v chaotic) | 38% (weakest 25% v direct) |
| chance | 180 s | 34% (weakest 20% v direct) | 44% (weakest 30% v low_block_counter) |
| shot | 15 s | 34% (weakest 30% v high_press) | 67% (weakest 60% v high_press) |
| shot | 30 s | 39% (weakest 30% v high_press) | 81% (weakest 80% v chaotic) |
| shot | 60 s | 51% (weakest 40% v high_press) | 89% (weakest 85% v high_press) |
| shot | 120 s | 67% (weakest 50% v high_press) | 95% (weakest 90% v high_press) |
| box | 15 s | 0% (weakest 0% v chaotic) | 0% (weakest 0% v chaotic) |
| box | 30 s | 3% (weakest 0% v direct) | 0% (weakest 0% v chaotic) |
| box | 60 s | 4% (weakest 0% v direct) | 0% (weakest 0% v chaotic) |
| box | 120 s | 7% (weakest 0% v direct) | 2% (weakest 0% v chaotic) |
| keep | 10 s | 75% (weakest 75% v chaotic) | 55% (weakest 55% v chaotic) |
| keep | 15 s | 40% (weakest 40% v chaotic) | 35% (weakest 35% v chaotic) |
| keep | 20 s | 31% (weakest 30% v chaotic) | 17% (weakest 15% v chaotic) |
| keep | 30 s | 15% (weakest 15% v chaotic) | 11% (weakest 10% v chaotic) |
| keep | 60 s | 0% (weakest 0% v chaotic) | 0% (weakest 0% v chaotic) |
| win_back | 10 s | 44% (weakest 25% v wing_play) | 50% (weakest 35% v wing_play) |
| win_back | 15 s | 59% (weakest 45% v wing_play) | 58% (weakest 50% v possession) |
| win_back | 20 s | 75% (weakest 60% v mid_block) | 75% (weakest 55% v possession) |
| win_back | 30 s | 88% (weakest 70% v possession) | 87% (weakest 70% v possession) |
| win_back | 60 s | 96% (weakest 80% v mid_block) | 97% (weakest 80% v mid_block) |
| protect | 60 s | 84% (weakest 80% v low_block_counter) | 93% (weakest 85% v wing_play) |
| protect | 120 s | 81% (weakest 75% v possession) | 91% (weakest 85% v possession) |
| protect | 180 s | 79% (weakest 65% v high_press) | 88% (weakest 80% v possession) |
| protect | 300 s | 73% (weakest 60% v high_press) | 86% (weakest 80% v high_press) |
