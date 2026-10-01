#!/bin/bash
# Wait for run 3's pipeline, then switch to opponent pool v2 and start its pipeline.
cd /home/user/SoccerSim
while pgrep -f "data/run_ml3b.sh" >/dev/null; do sleep 60; done
if ! grep -q PIPELINE_DONE data/run_ml3b.log; then echo "run 3 pipeline did not finish; not starting pool v2"; exit 1; fi
git add data/run_ml3b.log data/run_ml3b.sh data/chain_pool_v2.sh plays/generated_and_promoted
git commit -q -m "Run 3 (pool v1): pipeline log and promoted plays

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0181JhLqWhXqLGwGgcMDkkaL" || true
git merge --no-ff pool-v2-wip -m "Merge opponent pool v2

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0181JhLqWhXqLGwGgcMDkkaL" || { echo "merge failed"; exit 1; }
echo "merged pool v2; starting pipeline $(date)"
exec bash data/run_pool_v2.sh
