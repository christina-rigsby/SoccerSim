#!/bin/bash
# Pool v8 sequence (D-060), resumable step by step (finished steps are skipped on a relaunch):
# 1. full retraining with skill-aware instincts, including the generator league (no trial critic);
# 2. objective baselines on the current objectives: library, selector, main agent (generator), and
#    the objective-driven look-ahead; then adaptivity;
# 3. step 4: expert iteration on the current objectives, then the experts on the same evaluation.
cd "$(dirname "$0")/.."
TEAMS="library selector_latest main_latest lookahead_fast@objective"
grep -q PIPELINE_DONE data/pipeline_v8.log 2>/dev/null || SKIP_TRIAL=1 bash scripts/pipeline.sh >> data/pipeline_v8.log 2>&1 || exit 1
grep -q PIPELINE_DONE data/pipeline_v8.log || exit 1
echo "== baseline: start $(date +%T)"
python scripts/objectives.py --teams $TEAMS --scenarios 100 --conditions fresh \
  --out reports/objectives/baseline_pool_v8 || exit 1
echo "== adaptivity: start $(date +%T)"
python scripts/objectives.py --teams $TEAMS --scenarios 100 --objectives score_120 chance_60 keep_30 \
  --conditions our_forwards_slow their_defence_tiring --out reports/objectives/adaptivity_pool_v8 || exit 1
echo "== expert iteration: start $(date +%T)"
python scripts/expert.py --objective score_120 chance_60 keep_30 win_back_30 protect_180 --games 300 \
  --iterations 2 || exit 1
echo "== expert evaluation: start $(date +%T)"
python scripts/objectives.py --teams library expert0@objective expert@objective --scenarios 100 \
  --conditions fresh --out reports/objectives/expert_pool_v8 || exit 1
python scripts/objectives.py --teams library expert@objective --scenarios 100 --objectives score_120 chance_60 \
  keep_30 --conditions our_forwards_slow their_defence_tiring --out reports/objectives/expert_adaptivity_pool_v8 || exit 1
echo V8_QUEUE_DONE
