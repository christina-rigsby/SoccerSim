#!/bin/bash
# Play-variant evaluation (step 2): waits for data/eval_queue.sh to finish, then runs. Skips
# finished evaluations, so it can be relaunched after a restart.
cd "$(dirname "$0")/.."
while pgrep -f "data/eval_queue.sh" > /dev/null; do sleep 60; done
out=reports/evaluation/play_variants_pool_v4
if [ ! -f "$out/README.md" ]; then
  echo "== $out: start $(date +%T)"
  python scripts/evaluate_teams.py --teams library library+defensive_plus library+branchy library+prune_failing \
      library+branchy+defensive_plus+prune_failing --opponents styles --scenarios 20 --out "$out" 2>&1 | grep -v "episodes,"
  echo "== $out: done $(date +%T)"
fi
echo PLAYS_QUEUE_DONE
