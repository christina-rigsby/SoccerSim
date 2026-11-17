#!/bin/bash
# Which selector / main is best in the current library (pool v5)? Skipped once its report exists.
cd "$(dirname "$0")/.."
out=reports/evaluation/best_models_pool_v5
if [ ! -f "$out/README.md" ]; then
  echo "== $out: start $(date +%T)"
  python scripts/evaluate_teams.py --teams library selector selector_latest main main_latest --opponents styles \
      --scenarios 20 --out "$out" 2>&1 | grep -v "episodes,"
  echo "== $out: done $(date +%T)"
fi
echo BEST_QUEUE_DONE
