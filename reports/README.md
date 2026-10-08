# Reports you can open from the repo

Everything here is generated and committed so it can be viewed on GitHub (GIFs and Markdown
render in place). Each folder also has an `.html` page with the interactive replay viewer and
decision inspector: download it and open it in a browser.

| Folder | What it shows | Regenerate with |
|---|---|---|
| [`play_examples/`](play_examples/README.md) | One clip per play: our play (blue) and the opponent's counter-play (red) running at the same time, with the outcome | `python scripts/selfplay.py examples` |
| [`training_games/pool_v1/`](training_games/pool_v1/README.md) | Games from the Phase A self-play data the pool v1 critic and generator were trained on | `build_training_replays(...)` in `soccersim/viz/training_report.py` |
| [`training_games/pool_v2/`](training_games/pool_v2/README.md) | The same for opponent pool v2 | as above |
| [`run_3/generated_successes/`](run_3/generated_successes/README.md) (and later runs) | Every time a generated play succeeded during run N's league training or final evaluation, with the play's definition | `build_success_gallery(...)` in `soccersim/viz/play_examples.py` |
| `run_3/selfplay_report.html`, `run_3/selfplay_replays.html` | The Self-Play Lab report and highlight replays for run 3 | `python scripts/selfplay.py viz` |

Everything for one run is rebuilt with `python scripts/selfplay.py reports --run <N>`; the whole pipeline
with `bash scripts/pipeline.sh` (see the main README, "Reproducing the Self-Play Lab"). `out/` is a scratch
folder and is not committed.
