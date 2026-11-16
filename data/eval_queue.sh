#!/bin/bash
# Evaluation queue for the fair look-ahead and the look-ahead built on the selector.
# Each evaluation is skipped once its report exists, so the queue can be relaunched after a restart.
cd "$(dirname "$0")/.."
run() { out=$1; shift; [ -f "$out/README.md" ] && { echo "== $out: already done"; return; }
        echo "== $out: start $(date +%T)"; python scripts/evaluate_teams.py "$@" --out "$out" 2>&1 | grep -v "episodes," ; echo "== $out: done $(date +%T)"; }
run reports/evaluation/lookahead_fair_pool_v4 --teams library lookahead_fair --opponents styles --scenarios 20
run reports/evaluation/lookahead_on_selector_pool_v4 --teams library selector lookahead_fair_on_selector --opponents styles --scenarios 20
echo EVAL_QUEUE_DONE
