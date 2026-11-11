"""Is the critic limited by data, by model size, or by how predictable outcomes are?

    python scripts/critic_learning_curve.py                     # Phase A data of the current pool
    python scripts/critic_learning_curve.py --fractions 0.1 1.0 --epochs 4

Trains the critic on 10%, 25%, 50% and 100% of the Phase A training games at two model sizes
(the ``quick`` size used by the pipeline, and the larger ``spec`` size), always testing on the
same held-out 10% of games (whole games, so no situation from a test game is seen in training).
For each run it records, per epoch, the error on the training games and on the held-out games,
and keeps the best held-out epoch.

Error is shown as *skill over the per-play baseline*: ``1 - MSE / MSE(per-play average)``.
0% means no better than "how this play does on average"; higher is better.

Reading the result:

- held-out skill keeps rising with more data -> more data will help;
- the large model beats the small one on held-out games -> model size is a limit;
- neither helps, while training skill keeps rising -> the rest is noise the situation does
  not explain (or memorising training games).

Writes ``reports/critic_learning_curve/results.json`` and ``learning_curve.png``.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import torch  # noqa: E402
from torch import nn  # noqa: E402

from soccersim.config import load_config  # noqa: E402
from soccersim.generator.critic import Critic  # noqa: E402
from soccersim.generator.data import build_dataset, learning_target, play_ids  # noqa: E402
from soccersim.generator.train import _batches, _tensors, evaluate_critic, per_play_baseline  # noqa: E402
from soccersim.schema import load_library  # noqa: E402
from soccersim.selfplay.runs import data_paths  # noqa: E402

OUT = ROOT / "reports" / "critic_learning_curve"
SIZES = {"small (pipeline)": "quick", "large": "spec"}


def train_one(train, test, prof: str, epochs: int, lr: float, batch: int, seed: int, n_ids: int):
    cfg = load_config("training")
    enc, cc = cfg["encoder"][prof], cfg["critic"][prof]
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    critic = Critic(n_ids, enc, cc["d_model"], cc["layers"], cc["heads"])
    critic.y_mean.fill_(float(train.reward.mean()))
    critic.y_std.fill_(float(train.reward.std() + 1e-6))
    opt = torch.optim.AdamW(critic.parameters(), lr=lr, weight_decay=1e-4)
    base_test = per_play_baseline(train, test)
    probe_idx = rng.choice(len(train), min(len(train), len(test)), replace=False)
    probe = train.subset(probe_idx)
    base_probe = per_play_baseline(train, probe)
    hist = []
    for ep in range(epochs):
        critic.train()
        for b in _batches(len(train), batch, rng):
            x, h, tk, ident = _tensors(train, b)
            y = (torch.from_numpy(train.reward[b]) - critic.y_mean) / critic.y_std
            s = torch.from_numpy(train.success[b])
            v, sl = critic(x, h, tk, ident)
            loss = nn.functional.smooth_l1_loss(v, y) + 0.5 * nn.functional.binary_cross_entropy_with_logits(sl, s)
            opt.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(critic.parameters(), 1.0)
            opt.step()
        te = evaluate_critic(critic, test, base_test)
        tr = evaluate_critic(critic, probe, base_probe)
        hist.append({"epoch": ep + 1, "test_skill": 1 - te["mse"] / te["baseline_mse"],
                     "train_skill": 1 - tr["mse"] / tr["baseline_mse"], "test_corr": te["corr"],
                     "test_mse": te["mse"], "baseline_mse": te["baseline_mse"]})
    params = sum(p.numel() for p in critic.parameters())
    return hist, params


def plot(res: dict, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    colors = {"small (pipeline)": "#2a78d6", "large": "#eb6834"}
    ink, muted, grid = "#0b0b0b", "#52514e", "#e4e3df"
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2), sharey=False)
    fig.patch.set_facecolor("#fcfcfb")
    for ax, key, title in ((axes[0], "test_skill", "Held-out games (what matters)"),
                           (axes[1], "train_skill", "Training games")):
        ax.set_facecolor("#fcfcfb")
        for size, runs in res["runs"].items():
            xs = [r["train_games"] for r in runs]
            ys = [100 * (r["best"][key]) for r in runs]
            ax.plot(xs, ys, color=colors[size], lw=2, marker="o", ms=8, mec="#fcfcfb", mew=2,
                    label=f"{size}, {runs[0]['params'] / 1e3:.0f}k parameters")
            ax.annotate(f"{ys[-1]:.1f}%", (xs[-1], ys[-1]), textcoords="offset points", xytext=(8, -3),
                        color=ink, fontsize=9)
        ax.axhline(0, color=muted, lw=1, ls="--")
        ax.set_xscale("log")
        ax.set_xticks([r["train_games"] for r in next(iter(res["runs"].values()))])
        ax.get_xaxis().set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{int(v):,}"))
        ax.minorticks_off()
        ax.set_xlabel("training games (log scale)", color=muted)
        ax.set_title(title, color=ink, fontsize=11, loc="left")
        ax.grid(color=grid, lw=0.8)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        for s in ("left", "bottom"):
            ax.spines[s].set_color(grid)
        ax.tick_params(colors=muted)
    axes[0].set_ylabel("skill over per-play average (%)", color=muted)
    axes[0].legend(frameon=False, fontsize=9, loc="lower right")
    fig.suptitle("Critic: does more data or a bigger model help?  (best epoch; 0% = no better than "
                 "each play's average)", color=ink, fontsize=11, x=0.01, ha="left")
    fig.tight_layout()
    fig.savefig(path, dpi=150)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=None, help="self-play data root (default: the current pool's)")
    ap.add_argument("--fractions", type=float, nargs="+", default=[0.1, 0.25, 0.5, 1.0])
    ap.add_argument("--sizes", nargs="+", default=list(SIZES), choices=list(SIZES))
    ap.add_argument("--epochs", type=int, default=8)
    ap.add_argument("--lr", type=float, default=0.002)
    ap.add_argument("--batch", type=int, default=128)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()

    root = Path(a.root) if a.root else data_paths(load_config("league"))["selfplay"]
    lib = load_library()
    t0 = time.time()
    ds = build_dataset([root / "run=phase_a"], lib, seed=a.seed)
    train_all, test = ds.split(0.1, a.seed)
    eps = np.unique(train_all.episode)
    print(f"{len(ds)} decisions; {len(eps)} training games, {len(np.unique(test.episode))} held-out games; "
          f"target {learning_target()} ({time.time() - t0:.0f}s)", flush=True)
    order = np.random.default_rng(a.seed).permutation(eps)
    OUT.mkdir(parents=True, exist_ok=True)
    res = {"target": learning_target(), "decisions": len(ds), "test_games": int(len(np.unique(test.episode))),
           "test_rows": len(test), "epochs": a.epochs, "lr": a.lr, "runs": {}}
    for size in a.sizes:
        res["runs"][size] = []
        for f in sorted(a.fractions):
            keep = set(order[: max(1, int(round(f * len(eps))))])  # nested subsets: 10% within 25% ...
            tr = train_all.subset(np.where([e in keep for e in train_all.episode])[0])
            t1 = time.time()
            hist, params = train_one(tr, test, SIZES[size], a.epochs, a.lr, a.batch, a.seed, len(play_ids(lib)))
            best = max(hist, key=lambda h: h["test_skill"])
            run = {"fraction": f, "train_games": len(keep), "train_rows": len(tr), "params": params,
                   "best": best, "history": hist, "wall_s": round(time.time() - t1, 1)}
            res["runs"][size].append(run)
            print(f"  {size:17s} {f:>5.0%} ({len(keep):5d} games, {len(tr):6d} rows): held-out skill "
                  f"{100 * best['test_skill']:+.1f}% (epoch {best['epoch']}), training skill "
                  f"{100 * best['train_skill']:+.1f}%, corr {best['test_corr']:.3f}  [{run['wall_s']:.0f}s]",
                  flush=True)
            (OUT / "results.json").write_text(json.dumps(res, indent=1))
    plot(res, OUT / "learning_curve.png")
    print(f"wrote {OUT / 'results.json'} and learning_curve.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
