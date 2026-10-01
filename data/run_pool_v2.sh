#!/bin/bash
# Opponent pool v2 (D-045): regenerate Phase A data without the held-out styles, play the
# held-out reference games, retrain the critic and generator for the new pool, then train
# run 4 (fresh: the pool changed), promote, and rebuild the report.
set -e
cd /home/user/SoccerSim
# Keep the pool v1 base models (runs 1-3 also hold their own copies).
mkdir -p data/models/pool_v1
for f in critic.pt response.pt generator.pt meta.json critic_metrics.json generator_metrics.json; do
  [ -f data/models/$f ] && [ ! -f data/models/pool_v1/$f ] && cp data/models/$f data/models/pool_v1/$f
done
python scripts/selfplay.py --workers 4 phase-a --episodes 13500 --run-id phase_a
python scripts/selfplay.py --workers 4 heldout-ref --episodes 1500
python scripts/selfplay.py --workers 4 report
python scripts/selfplay.py --workers 4 train-critic
python -c "from soccersim.generator.train import compare_critic_ranking; import json; print('critic A/B', json.dumps(compare_critic_ranking('data/models', 60)))"
python scripts/selfplay.py --workers 4 pretrain-generator
python scripts/selfplay.py --workers 4 league
python scripts/selfplay.py --workers 4 promote
python -c "
from soccersim.viz.training_report import build_highlights, build_report
print(build_highlights('data/models', 'out/selfplay_replays.html', n_games=16, keep=4))
print(build_report('data/models', 'data/selfplay_pool_v2', 'out/selfplay_report.html'))"
echo PIPELINE_DONE
