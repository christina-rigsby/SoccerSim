#!/bin/bash
# Resumable training pipeline: run 3 on opponent pool v1, then switch to pool v2 (D-045) and
# train run 4. Each finished step leaves a marker in data/pipeline_state/, so after a
# container restart re-running this script picks up at the first unfinished step (the
# steps themselves resume too: cached mutation filter, Phase A skips logged episodes,
# league resumes an unfinished run).
set -e
cd /home/user/SoccerSim
STATE=data/pipeline_state
mkdir -p "$STATE"
step() {
  local name=$1; shift
  if [ -f "$STATE/$name.done" ]; then echo "== $name: already done"; return; fi
  echo "== $name: start $(date -u +%H:%M:%S)"
  "$@"
  touch "$STATE/$name.done"
  echo "== $name: done $(date -u +%H:%M:%S)"
}
report() {  # $1 = self-play data root, $2 = copy name
  python -c "
from soccersim.viz.training_report import build_highlights, build_report
print(build_highlights('data/models', 'out/selfplay_replays.html', n_games=16, keep=4))
print(build_report('data/models', '$1', 'out/selfplay_report.html'))"
  cp out/selfplay_report.html "out/$2_report.html"; cp out/selfplay_replays.html "out/$2_replays.html"
}
commit_run3() {
  git add plays/generated_and_promoted data/pipeline.log
  git commit -q -m "Run 3 (opponent pool v1): promoted plays and pipeline log

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0181JhLqWhXqLGwGgcMDkkaL" || true
}
merge_v2() {
  git merge-base --is-ancestor pool-v2-wip HEAD && return 0
  git merge --no-ff pool-v2-wip -m "Merge opponent pool v2

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0181JhLqWhXqLGwGgcMDkkaL"
}
keep_v1_models() {
  mkdir -p data/models/pool_v1
  for f in critic.pt response.pt generator.pt meta.json critic_metrics.json generator_metrics.json; do
    if [ -f "data/models/$f" ] && [ ! -f "data/models/pool_v1/$f" ]; then cp "data/models/$f" "data/models/pool_v1/$f"; fi
  done
}
critic_ab() {
  python -c "from soccersim.generator.train import compare_critic_ranking; import json; print('critic A/B', json.dumps(compare_critic_ranking('data/models', 60)))"
}
SP="python scripts/selfplay.py --workers 4"

# -- run 3, opponent pool v1 (run 2's regression gate already passed) --
step run3_pretrain   $SP pretrain-generator
step run3_league     $SP league --resume-unfinished
step run3_promote    $SP promote
step run3_report     report data/selfplay run3
step run3_commit     commit_run3

# -- opponent pool v2, run 4 (starts fresh: the pool changed) --
step v2_merge        merge_v2
step v2_keep_v1      keep_v1_models
step v2_phase_a      $SP phase-a --episodes 13500 --run-id phase_a
step v2_heldout_ref  $SP heldout-ref --episodes 1500
step v2_stats        $SP report
step v2_critic       $SP train-critic
step v2_critic_ab    critic_ab
step v2_pretrain     $SP pretrain-generator
step v2_league       $SP league --resume-unfinished
step v2_promote      $SP promote
step v2_report       report data/selfplay_pool_v2 run4
echo PIPELINE_DONE
