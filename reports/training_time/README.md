# Training time

Opponent pool v8 (the current one), measured from the logged games and the pipeline log (`python scripts/training_time_report.py`). Wall-clock times are on this machine (4 cores); a stage interrupted by a machine restart counts only its final, uninterrupted run. Game durations are simulated seconds: training games are scenario games that end at a goal or a change of possession.

## Per team

| Team | What its training is | Games played | Training wall-clock time |
|---|---|---|---|
| Selector | Phase A library games → critic → 4 refinement rounds of its own games | 14,700 (13,500 Phase A + 1,200 own) | 2.8 h (Phase A 24 min, critic 46 min, rounds 1.7 h) |
| Generator (main agent) | Phase A games → critic → pretraining (behaviour cloning + screening mutated plays in short trial games) → league | 13,596 (13,500 Phase A + 96 league) + the screening trials | 1.8 h (Phase A 24 min, critic 46 min, pretraining 25 min, league 15 min) |
| Look-ahead | none: it simulates candidate plays during the game | 0 | 0 |

## Game durations (simulated seconds)

| Games | Number | Median | 10th–90th percentile | Share in 0–5 / 5–10 / 10–20 / 20–30 / 30–60 / 60–120 / 120+ s |
|---|---|---|---|---|
| Phase A (library games, shared) | 13,500 | 18.1 s | 10.9–40.0 s | 1% / 5% / 51% / 23% / 21% / 0% / 0% |
| Selector refinement rounds | 1,200 | 17.8 s | 10.9–38.6 s | 0% / 4% / 54% / 22% / 18% / 0% / 0% |
| Generator league (PPO) | 96 | 15.3 s | 9.9–33.7 s | 0% / 10% / 58% / 19% / 12% / 0% / 0% |

## Cost when playing (wall-clock seconds per 120-second game, one core)

| Team | Seconds per game | Relative to the library |
|---|---|---|
| library | 3.0 | 1.0x |
| selector_latest | 3.7 | 1.2x |
| main_latest | 19.6 | 6.5x |
| lookahead_fast@score_120 | 54.2 | 18.1x |
