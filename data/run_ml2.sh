#!/bin/bash
set -e
cd /home/user/SoccerSim
python scripts/selfplay.py --workers 4 pretrain-generator
python scripts/selfplay.py --workers 4 league
python scripts/selfplay.py --workers 4 promote
echo PIPELINE_DONE
