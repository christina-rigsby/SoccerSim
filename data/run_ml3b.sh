#!/bin/bash
# Run 3, restarted after a container restart interrupted run_ml3.sh during generator
# pretraining (run 2's regression gate had already passed and been saved).
set -e
cd /home/user/SoccerSim
python scripts/selfplay.py --workers 4 pretrain-generator
python scripts/selfplay.py --workers 4 league
python scripts/selfplay.py --workers 4 promote
python -c "
from soccersim.viz.training_report import build_highlights, build_report
print(build_highlights('data/models', 'out/selfplay_replays.html', n_games=16, keep=4))
print(build_report('data/models', 'data/selfplay', 'out/selfplay_report.html'))"
echo PIPELINE_DONE
