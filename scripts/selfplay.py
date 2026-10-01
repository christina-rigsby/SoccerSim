"""Self-play pipeline CLI (spec §11, milestones M6–M9).

    python scripts/selfplay.py phase-a --episodes 13000 --workers 4      # >=200k decision records
    python scripts/selfplay.py report                                    # play frequency / success
    python scripts/selfplay.py fit-xt                                    # sim-derived xT
    python scripts/selfplay.py train-critic                              # M7 critic + response model
    python scripts/selfplay.py pretrain-generator                        # M8 BC + mutation filtering
    python scripts/selfplay.py league --updates 6                        # M9: next run (continues when safe)
    python scripts/selfplay.py promote                                   # latest run's elites -> run_<N>/
    python scripts/selfplay.py viz                                       # HTML report + replays

Defaults read ``configs/training.yaml`` (profile ``quick`` or ``spec``).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DATA = ROOT / "data" / "selfplay"
MODELS = ROOT / "data" / "models"
OUT = ROOT / "out"


def cmd_phase_a(a):
    from soccersim.selfplay.runner import phase_a_jobs, run_jobs

    jobs = phase_a_jobs(a.episodes, seed=a.seed, temperature=a.temperature, tracking_every=a.tracking_every,
                        run_id=a.run_id)
    out = run_jobs(jobs, a.root, a.run_id, workers=a.workers)
    print(json.dumps(out, indent=2))


def cmd_report(a):
    from soccersim.eval.reports import format_summary, summarize

    s = summarize(a.root)
    print(format_summary(s))
    OUT.mkdir(exist_ok=True)
    (OUT / "selfplay_summary.json").write_text(json.dumps(s, indent=2))


def cmd_fit_xt(a):
    from soccersim.eval.reports import fit_xt_from_runs

    print(json.dumps(fit_xt_from_runs(a.root, a.out), indent=2))


def cmd_train_critic(a):
    from soccersim.generator.train import train_critic_and_response

    print(json.dumps(train_critic_and_response(a.root, a.models, profile=a.profile, max_rows=a.max_rows), indent=2))


def cmd_pretrain(a):
    from soccersim.generator.train import pretrain_generator

    print(json.dumps(pretrain_generator(a.root, a.models, profile=a.profile, workers=a.workers,
                                        max_rows=a.max_rows), indent=2))


def cmd_league(a):
    from soccersim.selfplay.league import run_league

    mode = "fresh" if a.fresh else "force" if a.force_continue else "auto"
    run_dir = Path(a.models) / "runs" / f"run_{a.resume}" if a.resume else None
    print(json.dumps(run_league(a.models, a.root, updates=a.updates, profile=a.profile, workers=a.workers,
                                start_mode=mode, run_dir=run_dir), indent=2, default=str))


def cmd_promote(a):
    from soccersim.selfplay.promote import promote_elites

    run_dir = Path(a.models) / "runs" / f"run_{a.run}" if a.run else None
    print(json.dumps(promote_elites(a.models, a.root, profile=a.profile, workers=a.workers, run_dir=run_dir), indent=2))


def cmd_viz(a):
    from soccersim.viz.training_report import build_report

    print(build_report(a.models, a.root, OUT / "selfplay_report.html", fragment=a.fragment))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root", default=str(DATA), help="self-play log directory")
    p.add_argument("--models", default=str(MODELS), help="model / league directory")
    p.add_argument("--profile", default=None, help="training profile: quick | spec")
    p.add_argument("--workers", type=int, default=4)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("phase-a")
    s.add_argument("--episodes", type=int, default=240)
    s.add_argument("--seed", type=int, default=0)
    s.add_argument("--temperature", type=float, default=0.01)
    s.add_argument("--tracking-every", type=int, default=500)
    s.add_argument("--run-id", default="phase_a")
    s.set_defaults(fn=cmd_phase_a)
    sub.add_parser("report").set_defaults(fn=cmd_report)
    s = sub.add_parser("fit-xt")
    s.add_argument("--out", default=str(ROOT / "data" / "xt" / "xt_sim.json"))
    s.set_defaults(fn=cmd_fit_xt)
    for name, fn in (("train-critic", cmd_train_critic), ("pretrain-generator", cmd_pretrain)):
        s = sub.add_parser(name)
        s.add_argument("--max-rows", type=int, default=None)
        s.set_defaults(fn=fn)
    s = sub.add_parser("league", help="train the next league run (continues from the previous one when safe)")
    s.add_argument("--updates", type=int, default=None)
    s.add_argument("--fresh", action="store_true", help="start from the pretrained generator, not the previous run")
    s.add_argument("--force-continue", action="store_true",
                   help="continue from the previous run even if the opponent pool changed or its gate failed")
    s.add_argument("--resume", type=int, default=None, help="resume an existing run number instead of a new one")
    s.set_defaults(fn=cmd_league)
    s = sub.add_parser("promote", help="export the latest run's archive elites for review")
    s.add_argument("--run", type=int, default=None, help="run number (default: latest)")
    s.set_defaults(fn=cmd_promote)
    s = sub.add_parser("viz")
    s.add_argument("--fragment", action="store_true")
    s.set_defaults(fn=cmd_viz)
    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
