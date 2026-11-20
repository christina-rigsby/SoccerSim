#!/bin/bash
# After the pool v9 retraining (D-063): objective baselines on the agreed objectives, adaptivity, then
# step 4 (expert iteration) and its evaluation. Long objectives use fewer situations and search games
# (the look-ahead costs ~2 min of computing per 5-minute game). Resumable step by step.
cd "$(dirname "$0")/.."
until grep -q V9_RETRAIN_DONE data/v9_queue.log 2>/dev/null; do sleep 120; done
TEAMS="library selector_latest main_latest lookahead_fast@objective"
echo "== baseline short: start $(date +%T)"
python scripts/objectives.py --teams $TEAMS --scenarios 100 --objectives shot_60 keep_15 win_back_20 \
  --out reports/objectives/baseline_pool_v9_short || exit 1
echo "== baseline long: start $(date +%T)"
python scripts/objectives.py --teams library selector_latest main_latest --scenarios 50 \
  --objectives protect_300 chance_180 score_180 --out reports/objectives/baseline_pool_v9_long || exit 1
# The look-ahead on long games costs minutes per game: fewer situations, and no target-less score_180.
python scripts/objectives.py --teams library lookahead_fast@objective --scenarios 20 \
  --objectives protect_300 chance_180 --out reports/objectives/baseline_pool_v9_long_lookahead || exit 1
echo "== adaptivity: start $(date +%T)"
python scripts/objectives.py --teams library selector_latest main_latest --scenarios 100 \
  --objectives shot_60 keep_15 --conditions our_forwards_slow their_defence_tiring \
  --out reports/objectives/adaptivity_pool_v9 || exit 1
echo "== expert iteration: start $(date +%T)"
python scripts/expert.py --objective shot_60 keep_15 win_back_20 --games 300 --iterations 2 || exit 1
python scripts/expert.py --objective protect_300 chance_180 --games 100 --iterations 2 || exit 1
echo "== expert evaluation: start $(date +%T)"
python scripts/objectives.py --teams library expert0@objective expert@objective --scenarios 100 \
  --objectives shot_60 keep_15 win_back_20 --out reports/objectives/expert_pool_v9_short || exit 1
python scripts/objectives.py --teams library expert0@objective expert@objective --scenarios 50 \
  --objectives protect_300 chance_180 --out reports/objectives/expert_pool_v9_long || exit 1
python scripts/objectives.py --teams library expert@objective --scenarios 100 --objectives shot_60 keep_15 \
  --conditions our_forwards_slow their_defence_tiring --out reports/objectives/expert_adaptivity_pool_v9 || exit 1
echo V9_OBJECTIVES_DONE
