#!/bin/bash
# Pool v9 (D-062): full retraining with run 7's plays in the library (incl. the generator league,
# no trial critic). Objective baselines and step 4 follow once the redefined objectives are agreed.
cd "$(dirname "$0")/.."
grep -q PIPELINE_DONE data/pipeline_v9.log 2>/dev/null || SKIP_TRIAL=1 bash scripts/pipeline.sh >> data/pipeline_v9.log 2>&1 || exit 1
echo V9_RETRAIN_DONE
