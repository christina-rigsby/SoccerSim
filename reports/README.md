# Reports you can open from the repo

Everything here is generated and committed so it can be viewed on GitHub (GIFs and Markdown
render in place). Each folder also has an `.html` page with the interactive replay viewer and
decision inspector: download it and open it in a browser.

| Folder | What it shows | Regenerate with |
|---|---|---|
| [`play_examples/`](play_examples/README.md) | One clip per play: our play (blue) and the opponent's counter-play (red) running at the same time, with the outcome | `python scripts/selfplay.py examples` |
| [`training_games/pool_v1/`](training_games/pool_v1/README.md) | Games from the Phase A self-play data the pool v1 critic and generator were trained on | `build_training_replays(...)` in `soccersim/viz/training_report.py` |
| `training_games/pool_v2/` | The same for opponent pool v2 (after its Phase A run) | as above |
| `run_<N>/generated_successes/` | Every time a generated play succeeded during run N's league training or final evaluation, with the play's definition | `build_success_gallery(...)` in `soccersim/viz/play_examples.py` |
| `run_<N>/selfplay_report.html` | The Self-Play Lab report for run N | `python scripts/selfplay.py viz` |

`out/` is a scratch folder and is not committed.
