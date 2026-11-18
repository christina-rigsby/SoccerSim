"""A critic trained on the look-ahead team's trials ("trial critic").

The original critic learned from one outcome per decision (the play that was called), mixed with
everything that happened afterwards; it learned little beyond each play's average. The look-ahead
team instead tries several candidate plays *from the same moment* with shared random seeds, so
every decision gives a direct comparison: "here, A did this much better than B". This module:

1. **generates** that data: the look-ahead team (``record_state``) plays continuous games against
   the training styles and the plain library (never the held-out styles), and every look-ahead
   decision is saved with its situation, each candidate's side and its trial values
   (``data/trial_critic_pool_v<N>/chunk_*.jsonl.gz``; finished chunks are skipped on a rerun);
2. **trains** a critic (the existing architecture) to predict each candidate's trial value
   *relative to the other candidates of the same decision*, weighted by how many trials it got,
   because only the order within a decision matters for choosing a play;
3. reports, on held-out games, how often the critic's top pick is the trials' best play and how
   much trial value its pick loses, next to the base ranking's pick (the hand-written score, or
   the selector when the look-ahead was built on it).

The trained critic is saved as ``data/models/trial_critic/critic.pt``; the evaluation team
``trial_critic`` calls the play it rates highest (no simulation at game time).
"""

from __future__ import annotations

import gzip
import json
import time
from pathlib import Path
from typing import Any

import numpy as np

from ..config import load_config

OUT_NAME = "trial_critic"


def data_dir(root: str | Path = "data") -> Path:
    return Path(root) / f"trial_critic_pool_v{load_config('league').get('pool_version', 1)}"


def model_dir(models_dir: str | Path = "data/models") -> Path:
    return Path(models_dir) / OUT_NAME


# -- 1. data -------------------------------------------------------------------------------------


def _game(job: dict[str, Any]) -> list[dict[str, Any]]:
    from ..schema import load_library
    from ..sim.env import MatchEnv
    from ..sim.scenarios import Scenario
    from .policies import make_policy

    lib = load_library()
    sc = job["scenario"]
    env = MatchEnv(randomise=True, record_frames=False)
    env.reset(job["seed"], Scenario(**{k: v for k, v in sc.items() if k != "score"}, score=tuple(sc["score"])))
    rng = np.random.default_rng(job["seed"] + 1)
    me = make_policy(job["me"], lib, np.random.default_rng(rng.integers(1 << 31)))
    opp = make_policy(job["opp"], lib, np.random.default_rng(rng.integers(1 << 31)))
    pols = (me, opp) if job["side"] == 0 else (opp, me)
    res = env.run(*pols, max_time_s=job["max_time_s"], stop_on_goal=job.get("stop_on_goal", False),
                  stop_on_turnover=False)
    caps = np.round(env.state.caps, 3).tolist()
    out = []
    for d in res.decisions:
        if d.get("lookahead") and d.get("state") and d.get("team") == job["side"]:
            out.append({"game": job["game_id"], "opp": job["opp"]["id"], "t": d["t"], "state": d["state"],
                        "caps": d.get("caps", caps), "sides": d["sides"], "trials": d["lookahead"],
                        "scores": {c["play_id"]: c["score"] for c in d["candidates"] if c["feasible"]},
                        "chosen": d["chosen"]})
    return out


def generate(n_games: int, workers: int = 4, seed: int = 7, max_time_s: float = 60.0, chunk: int = 40,
             base: str | None = None, root: str | Path = "data", horizon_s: float = 12.0) -> Path:
    """Play ``n_games`` look-ahead games against the training opponents and save every look-ahead decision."""
    from ..sim.scenarios import SCENARIO_TYPES, sample_scenario
    from .evaluate import team_spec

    lcfg = load_config("league")
    opps = [s for s in lcfg["scripted_styles"] if s not in lcfg["held_out_styles"]] + ["library"]
    me = {"id": "lookahead", "kind": "lookahead", "record_state": True, "temperature": 0.01, "horizon_s": horizon_s}
    if base:
        me["base"] = team_spec(base)
    rng = np.random.default_rng(seed)
    jobs = []
    for g in range(n_games):
        sc = sample_scenario(rng, SCENARIO_TYPES[:-2] + ("random_open_play",), tuple(lcfg["formations"]))
        jobs.append({"game_id": f"T{g:05d}", "seed": int(rng.integers(1 << 31)), "scenario": sc.to_dict(),
                     "me": me, "opp": team_spec(opps[g % len(opps)]), "side": g % 2, "max_time_s": max_time_s})
    return write_chunks(jobs, data_dir(root), workers, chunk)


def write_chunks(jobs: list[dict[str, Any]], out: Path, workers: int = 4, chunk: int = 40) -> Path:
    """Play ``jobs`` (see :func:`_game`) in chunks, saving each chunk's decisions; finished chunks are skipped."""
    import multiprocessing as mp

    out.mkdir(parents=True, exist_ok=True)
    ctx = mp.get_context("fork")
    for c0 in range(0, len(jobs), chunk):
        path = out / f"chunk_{c0 // chunk:04d}.jsonl.gz"
        if path.exists():
            continue
        t0 = time.time()
        with ctx.Pool(workers) as pool:
            recs = [r for rs in pool.imap_unordered(_game, jobs[c0: c0 + chunk]) for r in rs]
        tmp = path.with_suffix(".tmp")
        with gzip.open(tmp, "wt") as f:
            for r in recs:
                f.write(json.dumps(r) + "\n")
        tmp.rename(path)
        print(f"  chunk {c0 // chunk}: {min(chunk, len(jobs) - c0)} games, {len(recs)} decisions, "
              f"{time.time() - t0:.0f}s", flush=True)
    return out


def load_records(root: str | Path = "data", path: str | Path | None = None) -> list[dict[str, Any]]:
    recs = []
    for p in sorted((Path(path) if path is not None else data_dir(root)).glob("chunk_*.jsonl.gz")):
        with gzip.open(p, "rt") as f:
            recs += [json.loads(line) for line in f]
    return recs


# -- 2. training ---------------------------------------------------------------------------------


def build(recs: list[dict[str, Any]], library) -> dict[str, np.ndarray]:
    """One row per (decision, candidate): situation, play, value relative to the decision's mean."""
    from ..generator.data import play_ids
    from ..generator.encoder import state_features
    from ..generator.grammar import BOS, EOS, PAD
    from ..generator.tokenizer import tokenize_library

    lib_tok = tokenize_library(library)
    ids = {p: i for i, p in enumerate(play_ids(library))}
    rows: dict[str, list] = {k: [] for k in ("x", "holder", "tokens", "ident", "y", "w", "group", "game", "play")}
    for gi, r in enumerate(recs):
        means = {p: float(np.mean(v["values"])) for p, v in r["trials"].items()}
        centre = float(np.mean(list(means.values())))
        for p, v in r["trials"].items():
            if p not in ids:
                continue
            feats, h = state_features(r["state"], np.asarray(r["caps"]), float(r["sides"].get(p, 1.0)))
            tk = (lib_tok.get(p) or [BOS, EOS])[:256]
            rows["x"].append(feats)
            rows["holder"].append(h)
            rows["tokens"].append(tk + [PAD] * (256 - len(tk)))
            rows["ident"].append(ids[p])
            rows["y"].append(means[p] - centre)
            rows["w"].append(len(v["values"]))
            rows["group"].append(gi)
            rows["game"].append(r["game"])
            rows["play"].append(p)
    return {k: np.asarray(v) for k, v in rows.items()}


def train(models_dir: str | Path = "data/models", root: str | Path = "data", epochs: int = 12, lr: float = 0.001,
          batch: int = 256, seed: int = 0, data_path: str | Path | None = None,
          out_path: str | Path | None = None) -> dict[str, Any]:
    """Train on the decisions in ``data_path`` (default: this pool's trial data) and save the critic
    to ``out_path`` (default: ``data/models/trial_critic``)."""
    import torch
    from torch import nn

    from ..generator.agent import save_model
    from ..generator.critic import Critic
    from ..generator.data import play_ids
    from ..schema import load_library

    torch.manual_seed(seed)
    lib = load_library()
    recs = load_records(root, data_path)
    d = build(recs, lib)
    games = np.unique(d["game"])
    rng = np.random.default_rng(seed)
    test_games = set(rng.choice(games, max(1, len(games) // 10), replace=False))
    te = np.array([g in test_games for g in d["game"]])
    tr = ~te
    cfg = load_config("training")
    enc, cc = cfg["encoder"]["quick"], cfg["critic"]["quick"]
    critic = Critic(len(play_ids(lib)), enc, cc["d_model"], cc["layers"], cc["heads"])
    critic.y_mean.fill_(0.0)
    critic.y_std.fill_(float(d["y"][tr].std() + 1e-6))
    opt = torch.optim.AdamW(critic.parameters(), lr=lr, weight_decay=1e-4)

    def tensors(idx):
        return (torch.from_numpy(d["x"][idx].astype(np.float32)), torch.from_numpy(d["holder"][idx].astype(np.int64)),
                torch.from_numpy(d["tokens"][idx].astype(np.int64)), torch.from_numpy(d["ident"][idx].astype(np.int64)))

    tr_idx = np.where(tr)[0]
    hist = []
    for ep in range(epochs):
        critic.train()
        for b in np.array_split(rng.permutation(tr_idx), max(1, len(tr_idx) // batch)):
            v, _ = critic(*tensors(b))
            y = torch.from_numpy(d["y"][b].astype(np.float32)) / critic.y_std
            w = torch.from_numpy(d["w"][b].astype(np.float32))
            loss = (w * (v - y) ** 2).sum() / w.sum()
            opt.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(critic.parameters(), 1.0)
            opt.step()
        m = evaluate(critic, d, np.where(te)[0], tensors)
        m["epoch"] = ep + 1
        hist.append(m)
        print(f"  epoch {ep + 1}: picks the trials' best {m['top1']:.1%} (base ranking {m['top1_score']:.1%}, "
              f"chance {m['top1_chance']:.1%}); trial value lost {m['regret']:.4f} "
              f"(base ranking {m['regret_score']:.4f})", flush=True)
    critic.eval()
    out = Path(out_path) if out_path is not None else model_dir(models_dir)
    out.mkdir(parents=True, exist_ok=True)
    save_model(critic, out / "critic.pt", ids=play_ids(lib))
    res = {"decisions": len(recs), "rows": int(len(d["y"])), "test_games": len(test_games), "history": hist}
    (out / "metrics.json").write_text(json.dumps(res, indent=1))
    return res


def evaluate(critic, d: dict[str, np.ndarray], idx: np.ndarray, tensors) -> dict[str, float]:
    """Within-decision choice quality on held-out decisions."""
    import torch

    with torch.no_grad():
        pred = np.concatenate([critic(*tensors(b))[0].numpy() for b in np.array_split(idx, max(1, len(idx) // 512))])
    p_of = dict(zip(idx, pred, strict=True))
    groups: dict[int, list[int]] = {}
    for i in idx:
        groups.setdefault(int(d["group"][i]), []).append(int(i))
    top1, top1_s, chance, regret, regret_s = [], [], [], [], []
    for rows in groups.values():
        if len(rows) < 2:
            continue
        y = d["y"][rows]
        best = int(np.argmax(y))
        k = int(np.argmax([p_of[i] for i in rows]))
        top1.append(k == best)
        regret.append(float(y[best] - y[k]))
        # The base ranking's pick (hand-written score, or the selector) is the first candidate:
        # candidates were tried in that order.
        top1_s.append(best == 0)
        regret_s.append(float(y[best] - y[0]))
        chance.append(1.0 / len(rows))
    return {"top1": float(np.mean(top1)), "top1_score": float(np.mean(top1_s)), "top1_chance": float(np.mean(chance)),
            "regret": float(np.mean(regret)), "regret_score": float(np.mean(regret_s)), "decisions": len(top1)}
