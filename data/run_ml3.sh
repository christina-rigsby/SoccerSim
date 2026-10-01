#!/bin/bash
# Run 3: gate run 2 (so run 3 may continue from it), pretrain with earlier promoted plays,
# train run 3, promote, and rebuild the report.
set -e
cd /home/user/SoccerSim
python -c "
from soccersim.selfplay.league import League
lg = League('data/models', 'data/selfplay', run_dir='data/models/runs/run_2')
print('run 2 gate', lg.regression_gate(workers=4))"
python scripts/selfplay.py --workers 4 pretrain-generator
python scripts/selfplay.py --workers 4 league
python scripts/selfplay.py --workers 4 promote
python -c "
from soccersim.viz.training_report import build_highlights, build_report
print(build_highlights('data/models', 'out/selfplay_replays.html', n_games=16, keep=4))
print(build_report('data/models', 'data/selfplay', 'out/selfplay_report.html'))"
echo PIPELINE_DONE
