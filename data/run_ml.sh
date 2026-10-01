#!/bin/bash
# Full Module 3 pipeline on the Phase A logs (quick profile).
set -e
cd /home/user/SoccerSim
python scripts/selfplay.py --workers 4 train-critic
python -c "from soccersim.generator.train import compare_critic_ranking; import json; print('critic A/B', json.dumps(compare_critic_ranking('data/models', 60)))"
python scripts/selfplay.py --workers 4 pretrain-generator
python scripts/selfplay.py --workers 4 league
python scripts/selfplay.py --workers 4 promote
echo PIPELINE_DONE
