"""Everything in ``reports/`` for one league run, rebuilt from the run's data in one call.

``python scripts/selfplay.py reports [--run N] [--fragment-dir DIR]`` writes:

- ``reports/run_<N>/selfplay_report.html``   the Self-Play Lab report
- ``reports/run_<N>/selfplay_replays.html``  highlight games of the trained agent
- ``reports/run_<N>/generated_successes/``  generated plays that worked (GIFs, README, page)
- ``reports/training_games/pool_v<V>/``       saved Phase A training games (once per pool)

and, with ``--fragment-dir``, the same report and pages as publishable fragments. Inputs are
the run's directory (``data/models/runs/run_<N>/``), the base models in ``data/models/``
and the pool's self-play logs (``configs/league.yaml: data.selfplay``); see README,
"Reproducing the Self-Play Lab".
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..config import REPO_ROOT, load_config
from ..selfplay.runs import data_paths, latest_run_dir, read_state, runs_root

REPORTS = REPO_ROOT / "reports"


def build_run_reports(models_dir: str | Path = REPO_ROOT / "data" / "models", run: int | None = None,
                      data_root: str | Path | None = None, fragment_dir: str | Path | None = None,
                      highlight_games: int = 16) -> dict[str, Any]:
    from .play_examples import build_success_gallery
    from .training_report import build_highlights, build_report, build_training_replays

    models = Path(models_dir)
    run_dir = runs_root(models) / f"run_{run}" if run else latest_run_dir(models)
    if run_dir is None or not run_dir.exists():
        raise FileNotFoundError(f"no league run under {runs_root(models)}")
    n = read_state(run_dir).get("run") or int(run_dir.name[4:])
    lcfg = load_config("league")
    root = Path(data_root) if data_root else data_paths(lcfg)["selfplay"]
    out = REPORTS / f"run_{n}"
    out.mkdir(parents=True, exist_ok=True)
    done: dict[str, Any] = {"run": n, "dir": str(out)}

    done["highlights"] = build_highlights(models, out / "selfplay_replays.html", n_games=highlight_games, keep=4,
                                          run_dir=run_dir)
    done["report"] = str(build_report(models, root, out / "selfplay_report.html", run_dir=run_dir))
    if (run_dir / "generated_successes" / "index.jsonl").exists():
        done["successes"] = build_success_gallery(run_dir, out / "generated_successes")
    pool = f"pool_v{lcfg.get('pool_version', 1)}"
    tg = REPORTS / "training_games" / pool
    if not (tg / "training_games.html").exists() and any((root / "run=phase_a" / "tracking").glob("*.json.gz")):
        build_training_replays(root, tg / "training_games.html", heading=f"Pool v{lcfg.get('pool_version', 1)} "
                               "training games", stride=2, gif_dir=tg)
        done["training_games"] = str(tg)
    if fragment_dir:
        fd = Path(fragment_dir)
        fd.mkdir(parents=True, exist_ok=True)
        build_report(models, root, fd / "selfplay_report.html", fragment=True, run_dir=run_dir)
        (fd / "selfplay_replays.html").write_text((out / "selfplay_replays.html").read_text())
        done["fragments"] = str(fd)
    return done
