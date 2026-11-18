#!/bin/bash
# Objective baselines under the new laws (pool v6): waits for the retraining, then runs
# (resumable: an interrupted evaluation continues from its games.partial.jsonl).
cd "$(dirname "$0")/.."
until grep -q PIPELINE_DONE data/pipeline_v6.log 2>/dev/null; do sleep 120; done
echo "== objectives fresh: start $(date +%T)"
python scripts/objectives.py --teams library selector_latest lookahead_fast@objective --scenarios 200 \
  --conditions fresh --out reports/objectives/baseline_pool_v6 || exit 1
echo "== objectives adaptivity: start $(date +%T)"
python scripts/objectives.py --teams library selector_latest lookahead_fast@objective --scenarios 100 \
  --objectives score_30 chance_30 keep_30 --conditions our_forwards_slow their_defence_tiring \
  --out reports/objectives/adaptivity_pool_v6 || exit 1
echo OBJECTIVE_QUEUE_DONE
