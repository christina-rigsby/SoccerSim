#!/bin/bash
# Confirmation run for the branchy plays (40 fresh scenarios). Skipped once its report exists.
cd "$(dirname "$0")/.."
out=reports/evaluation/branchy_confirm_pool_v4
if [ ! -f "$out/README.md" ]; then
  echo "== $out: start $(date +%T)"
  python scripts/evaluate_teams.py --teams library library+branchy library+branchy+prune_failing --opponents styles \
      --scenarios 40 --seed 3031 --out "$out" 2>&1 | grep -v "episodes,"
  echo "== $out: done $(date +%T)"
fi
echo CONFIRM_QUEUE_DONE
