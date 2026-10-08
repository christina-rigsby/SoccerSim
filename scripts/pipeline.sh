#!/bin/bash
# Reproduce the self-play pipeline and the Self-Play Lab reports from scratch (spec §11).
#
#   bash scripts/pipeline.sh            # quick profile (configs/training.yaml: profile)
#
# Stages, in order:
#   per opponent pool (configs/league.yaml; skipped once done for this pool):
#     phase-a        library self-play games -> data/<pool data>/run=phase_a (Parquet)
#     heldout-ref    library v held-out styles, for promotion medians only
#     stats          play usage summary (out/selfplay_summary.json)
#     train-critic   critic + response model -> data/models/{critic,response}.pt
#     critic-ab      ranking with vs without the critic (printed)
#   per league run (the next run, or the latest one if it never finished):
#     pretrain       generator: behaviour cloning + mutation filtering -> data/models/generator.pt
#     league         PPO league, held-out physics check, evaluation, regression gate, validation
#                    round-robin -> data/models/runs/run_<N>/
#     promote        archive elites -> plays/generated_and_promoted/run_<N>/
#     reports        everything in reports/run_<N>/ (scripts/selfplay.py reports)
#
# Every finished stage leaves a marker in data/pipeline_state/, so if the machine restarts,
# running this script again picks up at the first unfinished stage (stages also resume
# internally: logged games are skipped, mutation filtering is cached, behaviour cloning is
# checkpointed every epoch, and an unfinished league run is resumed).
set -euo pipefail
cd "$(dirname "$0")/.."
SP="python scripts/selfplay.py --workers ${WORKERS:-4}"
POOL=$(python -c "from soccersim.config import load_config; from soccersim.selfplay.runs import pool_fingerprint; print(pool_fingerprint(load_config('league')))")
RUN=$(python -c "
from soccersim.selfplay.runs import latest_run_dir, next_run_number, read_state
d = latest_run_dir('data/models')
print(read_state(d)['run'] if d is not None and not read_state(d).get('validation') else next_run_number('data/models'))")
STATE="data/pipeline_state/pool_${POOL}"
mkdir -p "$STATE/run_${RUN}"
step() {
  local marker=$1; shift
  if [ -f "$marker" ]; then echo "== $(basename "$marker"): already done"; return; fi
  echo "== $(basename "$marker"): start $(date -u +%H:%M:%S)"
  "$@"
  touch "$marker"
  echo "== $(basename "$marker"): done $(date -u +%H:%M:%S)"
}
critic_ab() {
  python -c "from soccersim.generator.train import compare_critic_ranking; import json; print('critic A/B', json.dumps(compare_critic_ranking('data/models', 60)))"
}
echo "opponent pool $POOL, league run $RUN"
step "$STATE/phase_a"      $SP phase-a --episodes "${EPISODES:-13500}" --run-id phase_a --tracking-every 500
step "$STATE/heldout_ref"  $SP heldout-ref --episodes 1500
step "$STATE/stats"        $SP report
step "$STATE/critic"       $SP train-critic
step "$STATE/critic_ab"    critic_ab
step "$STATE/run_${RUN}/pretrain" $SP pretrain-generator
step "$STATE/run_${RUN}/league"   $SP league --resume-unfinished
step "$STATE/run_${RUN}/promote"  $SP promote --run "$RUN"
step "$STATE/run_${RUN}/reports"  $SP reports --run "$RUN"
echo PIPELINE_DONE
