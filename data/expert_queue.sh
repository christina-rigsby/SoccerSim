#!/bin/bash
# Step 4 (expert iteration), after the objective baselines: per objective, 2 iterations of search
# (400 games) and distillation, then the networks on the objective evaluation. Resumable.
cd "$(dirname "$0")/.."
until grep -q OBJECTIVE_QUEUE_DONE data/objective_queue.log 2>/dev/null; do sleep 120; done
echo "== expert iteration: start $(date +%T)"
python scripts/expert.py --objective keep_30 win_back_8 protect_60 chance_30 score_30 --games 400 \
  --iterations 2 || exit 1
echo "== expert evaluation: start $(date +%T)"
python scripts/objectives.py --teams library expert0@objective expert@objective \
  --scenarios 200 --conditions fresh --out reports/objectives/expert_pool_v6 || exit 1
python scripts/objectives.py --teams library expert@objective --scenarios 100 \
  --objectives score_30 chance_30 keep_30 --conditions our_forwards_slow their_defence_tiring \
  --out reports/objectives/expert_adaptivity_pool_v6 || exit 1
echo EXPERT_QUEUE_DONE
