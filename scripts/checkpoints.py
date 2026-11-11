"""Save trained models to the repo (one version, replaced on every save) and restore them.

    python scripts/checkpoints.py save [--push]   # data/models -> checkpoints/ (and commit + push)
    python scripts/checkpoints.py restore         # checkpoints/ -> data/models (only if missing)
    python scripts/checkpoints.py status

Trained models live in ``data/models/``, which is git-ignored, so a session that moves to a
fresh machine used to lose them. ``save`` copies what is needed to use the models and to
resume training into ``checkpoints/`` (tracked), replacing the previous version:

- the base models: critic, response model, pretrained generator (+ its frozen copy), metrics,
  ``meta.json`` (which records the opponent pool they were trained for), and the generator
  pretraining's epoch checkpoint and mutation-filter cache when present;
- the learned selector (``data/models/selector/``);
- the latest league run (``data/models/runs/run_<N>/``): every learner, snapshot and the
  starting generator, the archive, the state (history, Elo, payoff, evaluation, gate,
  validation) and the saved clips of generated plays that worked;
- the pipeline's step markers (``data/pipeline_state/``), so ``scripts/pipeline.sh`` skips
  finished steps after a restore.

The self-play game logs (``data/selfplay_pool_v*/``, ~150 MB of Parquet) are not saved: too
large for git. After a move to a fresh machine, the pipeline regenerates the Phase A games
(about 35 minutes, deterministic) when a later step still needs them; trained models are not
retrained. Git keeps earlier versions in its history; only the working tree holds one version.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "data" / "models"
STATE = ROOT / "data" / "pipeline_state"
CK = ROOT / "checkpoints"

BASE_FILES = ("critic.pt", "response.pt", "generator.pt", "generator_ref.pt", "meta.json", "critic_metrics.json",
              "generator_metrics.json", "bc_checkpoint.pt", "mutation_filter_cache.pkl")
#: Pipeline steps that only produce game logs; after a restore without the logs they run again.
DATA_STEPS = ("phase_a", "heldout_ref", "stats")


def _latest_run() -> Path | None:
    runs = sorted((d for d in (MODELS / "runs").glob("run_*") if (d / "state.json").exists()),
                  key=lambda d: int(d.name[4:])) if (MODELS / "runs").exists() else []
    return runs[-1] if runs else None


def save(push: bool = False) -> dict:
    if not MODELS.exists():
        raise SystemExit("nothing to save: data/models does not exist")
    tmp = ROOT / "checkpoints.tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    (tmp / "models").mkdir(parents=True)
    saved = []
    for f in BASE_FILES:
        if (MODELS / f).exists():
            shutil.copy2(MODELS / f, tmp / "models" / f)
            saved.append(f"models/{f}")
    if (MODELS / "selector").exists():
        shutil.copytree(MODELS / "selector", tmp / "models" / "selector")
        saved.append("models/selector/")
    run = _latest_run()
    if run is not None:
        shutil.copytree(run, tmp / "models" / "runs" / run.name)
        saved.append(f"models/runs/{run.name}/")
    if STATE.exists():
        shutil.copytree(STATE, tmp / "pipeline_state")
        saved.append("pipeline_state/")
    meta = json.loads((MODELS / "meta.json").read_text()) if (MODELS / "meta.json").exists() else {}
    manifest = {"saved": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()), "files": saved,
                "pool_fingerprint": meta.get("critic_pool_fingerprint"), "latest_run": run.name if run else None}
    (tmp / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (tmp / "README.md").write_text(
        "# Saved models\n\nThe latest trained models, replaced on every save by `python scripts/checkpoints.py save`"
        " (one version). `python scripts/checkpoints.py restore` puts them back in `data/models/`; "
        "`scripts/pipeline.sh` does that by itself on a fresh machine. See `MANIFEST.json` for what is here.\n")
    shutil.rmtree(CK, ignore_errors=True)
    tmp.rename(CK)
    size = sum(f.stat().st_size for f in CK.rglob("*") if f.is_file())
    manifest["size_mb"] = round(size / 1e6, 1)
    print(f"saved {len(saved)} items to checkpoints/ ({manifest['size_mb']} MB)")
    if push:
        _commit_and_push(manifest)
    return manifest


def _commit_and_push(manifest: dict) -> None:
    def git(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)

    git("add", "-A", "checkpoints")
    if not git("diff", "--cached", "--quiet", "--", "checkpoints").returncode:
        print("checkpoints unchanged; nothing to commit")
        return
    msg = (f"Save trained models ({manifest.get('latest_run') or 'base models'}, {manifest['saved']})\n\n"
           "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>\n"
           "Claude-Session: https://claude.ai/code/session_0181JhLqWhXqLGwGgcMDkkaL")
    r = git("commit", "-q", "-m", msg, "--", "checkpoints")
    if r.returncode:
        print("commit failed:", r.stderr.strip())
        return
    branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    for delay in (0, 2, 4, 8, 16):
        time.sleep(delay)
        if not git("push", "-q", "-u", "origin", branch).returncode:
            print(f"committed and pushed to {branch}")
            return
    print("push failed; the commit is local and will go with the next push")


def restore(force: bool = False) -> bool:
    if not (CK / "MANIFEST.json").exists():
        print("no saved models in checkpoints/")
        return False
    if MODELS.exists() and any(MODELS.iterdir()) and not force:
        print("data/models already exists; nothing restored (use --force to overwrite)")
        return False
    MODELS.mkdir(parents=True, exist_ok=True)
    shutil.copytree(CK / "models", MODELS, dirs_exist_ok=True)
    if (CK / "pipeline_state").exists():
        shutil.copytree(CK / "pipeline_state", STATE, dirs_exist_ok=True)
        # The game logs are not saved: steps that only produce them must run again.
        sys.path.insert(0, str(ROOT))
        from soccersim.config import load_config
        from soccersim.selfplay.runs import data_paths

        if not any(data_paths(load_config("league"))["selfplay"].glob("run=phase_a")):
            for marker in STATE.rglob("*"):
                if marker.name in DATA_STEPS:
                    marker.unlink()
    m = json.loads((CK / "MANIFEST.json").read_text())
    print(f"restored models saved {m['saved']} ({m.get('latest_run') or 'no league run yet'})")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("save")
    s.add_argument("--push", action="store_true", help="commit checkpoints/ and push")
    r = sub.add_parser("restore")
    r.add_argument("--force", action="store_true")
    sub.add_parser("status")
    a = ap.parse_args()
    if a.cmd == "save":
        save(a.push)
    elif a.cmd == "restore":
        restore(a.force)
    else:
        print((CK / "MANIFEST.json").read_text() if (CK / "MANIFEST.json").exists() else "no saved models")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
