#!/bin/bash
# Fast look-ahead teams vs the best selector (pool v5 library). Waits for eval_queue_best.sh.
cd "$(dirname "$0")/.."
while pgrep -f "data/eval_queue_best.sh" > /dev/null; do sleep 60; done
out=reports/evaluation/lookahead_fast_pool_v5
if [ ! -f "$out/README.md" ]; then
  echo "== $out: start $(date +%T)"
  python scripts/evaluate_teams.py --teams selector library lookahead_fast lookahead_fast_key --opponents styles \
      --scenarios 20 --out "$out" 2>&1 | grep -v "episodes,"
  echo "== $out: done $(date +%T)"
fi
echo FAST_QUEUE_DONE
