"""Training for Module 3 (spec §11 Phases A–B; M7–M8).

- :func:`train_critic_and_response` — the critic (EPV delta + success) and the response
  model (opponent's next play + outcome events), with a per-play-mean baseline the critic
  must beat on held-out episodes (M7 acceptance).
- :func:`pretrain_generator` — behaviour cloning on logged library choices plus filtered
  mutation self-imitation; reports grammar validity (target > 99 %) and generated vs
  library EPV delta in matched scenarios (M8 acceptance).
"""

from __future__ import annotations

import json
import multiprocessing as mp
import time
from pathlib import Path
from typing import Any

import numpy as np
import torch
from torch import nn

from ..config import load_config
from ..schema import load_library
from ..schema.loader import play_to_dict
from ..schema.models import Play
from ..schema.validate import PlayValidationError, parse_play
from ..selfplay.rewards import play_reward
from ..sim.play_scenarios import PLAY_SCENARIOS, run_play
from ..sim.scenarios import Scenario
from .agent import save_model
from .critic import Critic, ResponseModel
from .data import Dataset, build_dataset, opp_classes, play_ids
from .encoder import state_features
from .grammar import PAD, PHASES
from .model import PlayGenerator, pad_batch
from .mutate import mutate
from .tokenizer import TokenizeError, tokenize_play


def _profile(name: str | None) -> tuple[dict, str]:
    cfg = load_config("training")
    return cfg, name or cfg["profile"]


def _tensors(ds: Dataset, idx: np.ndarray):
    x = torch.from_numpy(ds.x[idx].astype(np.float32))
    h = torch.from_numpy(ds.holder[idx].astype(np.int64))
    tk = torch.from_numpy(ds.tokens[idx].astype(np.int64))
    L = int((tk != PAD).sum(1).max().item()) if len(idx) else 1
    tk = tk[:, : max(L, 1)]
    ident = torch.from_numpy(ds.ident[idx].astype(np.int64))
    return x, h, tk, ident


def per_play_baseline(train: Dataset, test: Dataset) -> np.ndarray:
    means = {}
    for pid in np.unique(train.chosen):
        means[pid] = float(train.reward[train.chosen == pid].mean())
    glob = float(train.reward.mean())
    return np.array([means.get(p, glob) for p in test.chosen], dtype=np.float32)


def _batches(n: int, bs: int, rng: np.random.Generator, shuffle: bool = True):
    idx = rng.permutation(n) if shuffle else np.arange(n)
    for i in range(0, n, bs):
        yield idx[i: i + bs]


# -- critic + response ---------------------------------------------------------------------


def train_critic_and_response(root: str | Path, out_dir: str | Path, profile: str | None = None,
                              max_rows: int | None = None, seed: int = 0) -> dict[str, Any]:
    cfg, prof = _profile(profile)
    torch.manual_seed(seed)
    torch.set_num_threads(max(1, mp.cpu_count()))
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    lib = load_library()
    t0 = time.time()
    ds = build_dataset(root, lib, max_rows=max_rows or cfg["critic"][prof].get("max_rows"), seed=seed)
    train, test = ds.split(0.1, seed)
    build_s = time.time() - t0
    enc = cfg["encoder"][prof]
    cc = cfg["critic"][prof]
    rng = np.random.default_rng(seed)

    # Critic.
    critic = Critic(len(play_ids(lib)), enc, cc["d_model"], cc["layers"], cc["heads"])
    critic.y_mean.fill_(float(train.reward.mean()))
    critic.y_std.fill_(float(train.reward.std() + 1e-6))
    opt = torch.optim.AdamW(critic.parameters(), lr=cc["lr"], weight_decay=1e-4)
    base = per_play_baseline(train, test)
    hist = []
    for ep in range(cc["epochs"]):
        critic.train()
        tot = 0.0
        for b in _batches(len(train), cc["batch"], rng):
            x, h, tk, ident = _tensors(train, b)
            y = (torch.from_numpy(train.reward[b]) - critic.y_mean) / critic.y_std
            s = torch.from_numpy(train.success[b])
            v, sl = critic(x, h, tk, ident)
            loss = nn.functional.smooth_l1_loss(v, y) + 0.5 * nn.functional.binary_cross_entropy_with_logits(sl, s)
            opt.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(critic.parameters(), 1.0)
            opt.step()
            tot += loss.item() * len(b)
        m = evaluate_critic(critic, test, base)
        m.update(epoch=ep + 1, train_loss=tot / len(train))
        hist.append(m)
        print(f"  critic epoch {ep + 1}: test MSE {m['mse']:.6f} vs per-play baseline {m['baseline_mse']:.6f}, "
              f"success acc {m['success_acc']:.3f}", flush=True)
    critic.eval()
    save_model(critic, out / "critic.pt", ids=play_ids(lib))

    # Response model.
    rc = cfg["response"][prof]
    ocl = opp_classes(lib)
    resp = ResponseModel(len(play_ids(lib)), len(ocl), enc, cc["d_model"], cc["layers"], cc["heads"])
    opt = torch.optim.AdamW(resp.parameters(), lr=rc["lr"], weight_decay=1e-4)
    rhist = []
    for ep in range(rc["epochs"]):
        resp.train()
        for b in _batches(len(train), cc["batch"], rng):
            x, h, tk, ident = _tensors(train, b)
            lo, le = resp(x, h, tk, ident)
            loss = nn.functional.cross_entropy(lo, torch.from_numpy(train.opp[b].astype(np.int64))) + \
                nn.functional.binary_cross_entropy_with_logits(le, torch.from_numpy(train.events[b]))
            opt.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(resp.parameters(), 1.0)
            opt.step()
        m = evaluate_response(resp, train, test)
        m["epoch"] = ep + 1
        rhist.append(m)
        print(f"  response epoch {ep + 1}: opp-play acc {m['opp_acc']:.3f} (majority {m['opp_majority']:.3f}), "
              f"event BCE {m['event_bce']:.4f} (base rate {m['event_base_bce']:.4f})", flush=True)
    resp.eval()
    save_model(resp, out / "response.pt", ids=play_ids(lib), opp=ocl)

    result = {
        "rows": len(ds), "train": len(train), "test": len(test), "dataset_build_s": round(build_s, 1),
        "critic": hist[-1], "critic_history": hist, "response": rhist[-1], "response_history": rhist,
        "critic_beats_baseline": hist[-1]["mse"] < hist[-1]["baseline_mse"],
    }
    (out / "critic_metrics.json").write_text(json.dumps(result, indent=2))
    meta = _meta(out)
    meta.update(profile=prof, critic_trained=time.strftime("%Y-%m-%d %H:%M"), data_root=str(root))
    (out / "meta.json").write_text(json.dumps(meta, indent=2))
    return {k: v for k, v in result.items() if not k.endswith("history")}


@torch.no_grad()
def evaluate_critic(critic: Critic, test: Dataset, baseline: np.ndarray, bs: int = 512) -> dict[str, float]:
    critic.eval()
    preds, sp = [], []
    for b in _batches(len(test), bs, np.random.default_rng(0), shuffle=False):
        v, s = critic.value(*_tensors(test, b))
        preds.append(v.numpy())
        sp.append(s.numpy())
    p = np.concatenate(preds)
    s = np.concatenate(sp)
    y = test.reward
    return {"mse": float(np.mean((p - y) ** 2)), "baseline_mse": float(np.mean((baseline - y) ** 2)),
            "mean_mse": float(np.mean((y.mean() - y) ** 2)),
            "success_acc": float(np.mean((s > 0.5) == (test.success > 0.5))),
            "corr": float(np.corrcoef(p, y)[0, 1]) if len(y) > 2 and p.std() > 0 else 0.0}


@torch.no_grad()
def evaluate_response(resp: ResponseModel, train: Dataset, test: Dataset, bs: int = 512) -> dict[str, float]:
    resp.eval()
    acc, bce = [], []
    for b in _batches(len(test), bs, np.random.default_rng(0), shuffle=False):
        lo, le = resp(*_tensors(test, b))
        acc.append((lo.argmax(-1).numpy() == test.opp[b]).astype(float))
        bce.append(nn.functional.binary_cross_entropy_with_logits(
            le, torch.from_numpy(test.events[b]), reduction="none").mean(-1).numpy())
    maj = np.bincount(train.opp).argmax()
    rate = np.clip(train.events.mean(0), 1e-4, 1 - 1e-4)
    base_bce = -(test.events * np.log(rate) + (1 - test.events) * np.log(1 - rate)).mean()
    return {"opp_acc": float(np.concatenate(acc).mean()), "opp_majority": float(np.mean(test.opp == maj)),
            "event_bce": float(np.concatenate(bce).mean()), "event_base_bce": float(base_bce)}


def _meta(out: Path) -> dict:
    p = out / "meta.json"
    return json.loads(p.read_text()) if p.exists() else {}


# -- mutation filtering ------------------------------------------------------------------------


def _eval_play_job(job: dict) -> dict:
    """Forced rollouts of one play in scenarios matching it; returns rewards and start states."""
    lib = load_library()
    play = parse_play(job["play"])
    if "scenario_types" in job:
        types, attacking = tuple(job["scenario_types"]), int(job.get("attacking", 0))
    else:
        types, attacking = PLAY_SCENARIOS[job["parent"]]
    rewards, states = [], []
    for seed in job["seeds"]:
        sc = Scenario(type=types[seed % len(types)], attacking_team=attacking)
        run = run_play(lib, play.id, seed, sc, max_time_s=20.0, extra=play)
        rec = run.forced_record(play.id)
        if rec is None:
            continue
        rewards.append(play_reward(rec, play.phase))
        if rec.get("state"):
            states.append((rec["state"], np.asarray(run.result.caps, dtype=np.float32).tolist(), rec["side"]))
        if len(rewards) >= job["rollouts"]:
            break
    return {"id": play.id, "parent": job["parent"], "rewards": rewards, "states": states}


def _eval_generated_job(job: dict) -> dict:
    """Forced rollouts of one generated play in scenarios matching its start band."""
    from ..selfplay.league import BAND_SCENARIOS

    lib = load_library()
    play = parse_play(job["play"])
    typ = BAND_SCENARIOS.get(job["band"], "random_open_play")
    rewards = []
    for seed in job["seeds"]:
        run = run_play(lib, play.id, seed, Scenario(type=typ, attacking_team=0), max_time_s=20.0, extra=play,
                       opponent_style=job.get("opponent"))
        rec = run.forced_record(play.id)
        if rec is None:
            continue
        rewards.append(play_reward(rec, play.phase))
        if len(rewards) >= job["rollouts"]:
            break
    return {"id": play.id, "rewards": rewards}


def _parent_scenarios(play: Play) -> dict[str, Any]:
    """Scenario types matching a mutation parent: library plays by id, promoted plays by start band."""
    if play.id in PLAY_SCENARIOS:
        return {}
    from ..selfplay.league import BAND_SCENARIOS

    band = ((play.provenance or {}).get("archive_cell") or {}).get("band", "mid_opp")
    return {"scenario_types": [BAND_SCENARIOS.get(band, "random_open_play")], "attacking": 0}


def mutation_filter(lib: dict[str, Play], mcfg: dict, seed: int = 0, workers: int = 4,
                    extra_parents: list[Play] | None = None) -> dict[str, Any]:
    """Mutate possession plays, evaluate in matched scenarios, keep the top quantile.

    Parents are the library's possession plays plus ``extra_parents`` — earlier runs'
    promoted plays (option 1), so a run can refine and adapt them.
    """
    rng = np.random.default_rng(seed)
    parents = [p for p in lib.values() if p.phase in PHASES and p.id in PLAY_SCENARIOS]
    parents += [p for p in (extra_parents or []) if p.phase in PHASES]
    jobs = []
    seeds = list(range(1000, 1000 + mcfg["rollouts"] * 4))
    for parent in parents:
        where = _parent_scenarios(parent)
        jobs.append({"play": play_to_dict(parent), "parent": parent.id, "seeds": seeds, "rollouts": mcfg["rollouts"],
                     **where})
        made = 0
        for _ in range(mcfg["mutants_per_play"] * 4):
            m = mutate(parent, rng)
            if m is None:
                continue
            try:
                tokenize_play(m)
            except TokenizeError:
                continue
            jobs.append({"play": play_to_dict(m), "parent": parent.id, "seeds": seeds, "rollouts": mcfg["rollouts"],
                         **where})
            made += 1
            if made >= mcfg["mutants_per_play"]:
                break
    if workers > 1:
        with mp.get_context("fork").Pool(workers) as pool:
            results = pool.map(_eval_play_job, jobs, chunksize=1)
    else:
        results = [_eval_play_job(j) for j in jobs]
    by_parent: dict[str, list[dict]] = {}
    for r in results:
        if len(r["rewards"]) >= max(2, mcfg["rollouts"] // 2):
            r["mean"] = float(np.mean(r["rewards"]))
            by_parent.setdefault(r["parent"], []).append(r)
    survivors = []
    summary = {}
    for parent, rs in by_parent.items():
        base = next((r for r in rs if r["id"] == parent), None)
        muts = [r for r in rs if r["id"] != parent]
        if not muts:
            continue
        cut = np.quantile([r["mean"] for r in muts], 1 - mcfg["keep_quantile"])
        keep = [r for r in muts if r["mean"] >= cut]
        survivors.extend(keep)
        summary[parent] = {"parent_mean": base["mean"] if base else None, "mutants": len(muts),
                           "kept": len(keep), "best_mutant_mean": max(r["mean"] for r in muts)}
    by_id = {j["play"]["id"]: j["play"] for j in jobs}
    plays = {r["id"]: parse_play(by_id[r["id"]]) for r in survivors}
    extra_ids = {p.id for p in extra_parents or []}
    prior_evals = [r for r in results if r["id"] in extra_ids]
    return {"survivors": survivors, "plays": plays, "summary": summary, "evaluated": len(results),
            "prior_parents": prior_evals,
            "survivors_from_prior": sum(1 for r in survivors if r["parent"] in extra_ids)}


def _cached_mutation_filter(out: Path, lib: dict[str, Play], mcfg: dict, seed: int, workers: int,
                            prior: list[Play]) -> dict[str, Any]:
    import hashlib
    import pickle

    key = hashlib.sha1(json.dumps({
        "mcfg": mcfg, "seed": seed, "library": sorted(play_to_dict(p)["id"] + str(p.version) for p in lib.values()),
        "prior": sorted(json.dumps(play_to_dict(p), sort_keys=True, default=str) for p in prior),
        "league": load_config("league"),
    }, sort_keys=True, default=str).encode()).hexdigest()
    cache = Path(out) / "mutation_filter_cache.pkl"
    if cache.exists():
        try:
            data = pickle.loads(cache.read_bytes())
            if data.get("key") == key:
                print("  mutation filtering: reusing the cached result of an interrupted pretraining", flush=True)
                return data["mf"]
        except Exception:  # noqa: BLE001 - a corrupt cache is simply recomputed
            pass
    mf = mutation_filter(lib, mcfg, seed, workers, extra_parents=prior)
    tmp = cache.with_suffix(".tmp")
    tmp.write_bytes(pickle.dumps({"key": key, "mf": mf}))
    tmp.replace(cache)
    return mf


# -- behaviour cloning ------------------------------------------------------------------------------


def pretrain_generator(root: str | Path, out_dir: str | Path, profile: str | None = None, workers: int = 4,
                       max_rows: int | None = None, seed: int = 0,
                       promoted_root: str | Path | None = None) -> dict[str, Any]:
    cfg, prof = _profile(profile)
    torch.manual_seed(seed)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    lib = load_library()
    t0 = time.time()
    cap = cfg["bc"][prof].get("max_examples")
    ds = build_dataset(root, lib, max_rows=max_rows or (4 * cap if cap else None), seed=seed + 1)
    keep = np.array([ph in PHASES for ph in ds.phase]) & ((ds.tokens != PAD).sum(1) > 2) & \
        np.array([c in lib for c in ds.chosen])
    idx = np.where(keep)[0]
    bc = ds.subset(idx[:cap] if cap else idx)
    print(f"  BC examples from logs: {len(bc)}", flush=True)

    # Earlier runs' promoted plays (all runs that exist before the next league run).
    from ..selfplay.runs import PROMOTED_DIR, next_run_number, prior_promoted

    proot = Path(promoted_root) if promoted_root else PROMOTED_DIR
    prior = prior_promoted(before_run=next_run_number(out, proot), root=proot)
    print(f"  earlier promoted plays: {len(prior)} from runs "
          f"{sorted({p.provenance.get('run') for p in prior}) or 'none'}", flush=True)

    # Option 1: they are mutation parents alongside the library. The filter is the slow part
    # of pretraining, so its result is cached and reused if pretraining is restarted.
    mf = _cached_mutation_filter(out, lib, cfg["mutation"][prof], seed, workers, prior)
    print(f"  mutation filtering: {mf['evaluated']} plays evaluated, {len(mf['survivors'])} survivors "
          f"({mf['survivors_from_prior']} from earlier promoted plays)", flush=True)
    mx, mh, mt = [], [], []

    def add_examples(states, toks):
        for st, caps, side in states:
            f, h = state_features(st, np.asarray(caps, dtype=np.float32), float(side or 1.0))
            mx.append(f)
            mh.append(h)
            mt.append(toks)

    for r in mf["survivors"]:
        add_examples(r["states"], tokenize_play(mf["plays"][r["id"]]))
    # Option 2: imitate the earlier promoted plays themselves, in the matched states they were replayed in.
    prior_by_id = {p.id: p for p in prior}
    prior_examples = 0
    for r in mf["prior_parents"]:
        try:
            toks = tokenize_play(prior_by_id[r["id"]])
        except TokenizeError:
            continue
        before = len(mt)
        add_examples(r["states"], toks)
        prior_examples += len(mt) - before

    gc = cfg["generator"][prof]
    enc = cfg["encoder"][prof]
    bcc = cfg["bc"][prof]
    gen = PlayGenerator(enc, gc["d_model"], gc["layers"], gc["heads"], 320)
    torch.set_num_threads(max(1, mp.cpu_count()))
    opt = torch.optim.AdamW(gen.parameters(), lr=bcc["lr"], weight_decay=1e-4)
    train, test = bc.split(0.1, seed)
    # Oversample survivors so filtered self-imitation is visible next to thousands of log rows.
    extra_x = np.asarray(mx, dtype=np.float16) if mx else np.zeros((0, 23, bc.x.shape[2]), np.float16)
    extra_h = np.asarray(mh, dtype=np.int16)
    extra_t = mt
    rng = np.random.default_rng(seed)
    hist = []
    # Behaviour cloning takes the better part of an hour: checkpoint every epoch so an
    # interrupted pretraining resumes where it stopped.
    ckpt_path = out / "bc_checkpoint.pt"
    ckpt_key = json.dumps({"bc": len(bc), "extra": len(extra_t), "cfg": bcc, "seed": seed,
                           "lib": sorted(lib)}, sort_keys=True, default=str)
    start_ep = 0
    if ckpt_path.exists():
        ck = torch.load(ckpt_path, weights_only=False)
        if ck.get("key") == ckpt_key:
            gen.load_state_dict(ck["gen"])
            opt.load_state_dict(ck["opt"])
            rng.bit_generator.state = ck["rng"]
            torch.set_rng_state(ck["torch_rng"])
            hist, start_ep = ck["hist"], ck["epoch"]
            print(f"  BC: resuming after epoch {start_ep} from an interrupted pretraining", flush=True)
    for ep in range(start_ep, bcc["epochs"]):
        gen.train()
        n_extra = min(len(extra_t) * 3, len(train) // 3)
        ex_idx = rng.integers(0, len(extra_t), n_extra) if len(extra_t) else np.zeros(0, int)
        order = rng.permutation(len(train) + n_extra)
        tot, cnt = 0.0, 0
        for i in range(0, len(order), bcc["batch"]):
            sel = order[i: i + bcc["batch"]]
            a = sel[sel < len(train)]
            b = ex_idx[sel[sel >= len(train)] - len(train)]
            xs = [train.x[a]] + ([extra_x[b]] if len(b) else [])
            hs = [train.holder[a]] + ([extra_h[b]] if len(b) else [])
            seqs = [list(r[r != PAD]) for r in train.tokens[a]] + [extra_t[k] for k in b]
            x = torch.from_numpy(np.concatenate(xs).astype(np.float32))
            h = torch.from_numpy(np.concatenate(hs).astype(np.int64))
            tk = pad_batch(seqs)
            logits = gen(x, h, tk)
            loss = nn.functional.cross_entropy(logits.reshape(-1, logits.shape[-1]), tk[:, 1:].reshape(-1),
                                               ignore_index=PAD)
            opt.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(gen.parameters(), 1.0)
            opt.step()
            tot += loss.item() * len(sel)
            cnt += len(sel)
        m = {"epoch": ep + 1, "train_loss": tot / max(cnt, 1), **_bc_eval(gen, test)}
        hist.append(m)
        print(f"  BC epoch {ep + 1}: loss {m['train_loss']:.3f}, held-out token acc {m['token_acc']:.3f}", flush=True)
        tmp = ckpt_path.with_suffix(".tmp")
        torch.save({"key": ckpt_key, "epoch": ep + 1, "gen": gen.state_dict(), "opt": opt.state_dict(),
                    "rng": rng.bit_generator.state, "torch_rng": torch.get_rng_state(), "hist": hist}, tmp)
        tmp.replace(ckpt_path)
    gen.eval()
    save_model(gen, out / "generator.pt")
    save_model(gen, out / "generator_ref.pt")        # frozen Phase B reference for the PPO KL term
    ckpt_path.unlink(missing_ok=True)
    validity = generator_validity(gen, test, n_states=60, per_state=4, seed=seed)
    print(f"  validity: {validity['validity']:.3%} over {validity['sampled']} samples", flush=True)
    matched = compare_generated_vs_library(out, n_episodes={"smoke": 2, "quick": 24}.get(prof, 120), workers=workers)
    print(f"  matched scenarios: generated {matched['generated_mean']:.4f} vs library {matched['library_mean']:.4f} "
          f"mean play reward -> {'meets' if matched['meets_target'] else 'below'} the 80% target", flush=True)
    result = {"bc_examples": len(bc), "mutation": {k: v for k, v in mf.items() if k in ("summary", "evaluated")},
              "survivors": len(mf["survivors"]), "survivor_examples": len(extra_t),
              "prior_promoted": {"plays": len(prior), "runs": sorted({p.provenance.get("run") for p in prior}),
                                 "imitation_examples": prior_examples,
                                 "mutant_survivors": mf["survivors_from_prior"]}, "history": hist,
              "validity": validity, "matched": matched, "elapsed_s": round(time.time() - t0, 1)}
    (out / "generator_metrics.json").write_text(json.dumps(result, indent=2, default=str))
    meta = _meta(out)
    meta.update(generator_trained=time.strftime("%Y-%m-%d %H:%M"), profile=prof)
    (out / "meta.json").write_text(json.dumps(meta, indent=2))
    return {k: v for k, v in result.items() if k != "history"}


@torch.no_grad()
def _bc_eval(gen: PlayGenerator, test: Dataset, n: int = 512) -> dict[str, float]:
    gen.eval()
    idx = np.arange(min(n, len(test)))
    if not len(idx):
        return {"token_acc": 0.0}
    x = torch.from_numpy(test.x[idx].astype(np.float32))
    h = torch.from_numpy(test.holder[idx].astype(np.int64))
    tk = pad_batch([list(r[r != PAD]) for r in test.tokens[idx]])
    pred = gen(x, h, tk).argmax(-1)
    tgt = tk[:, 1:]
    mask = tgt != PAD
    return {"token_acc": float(((pred == tgt) & mask).sum() / mask.sum())}


@torch.no_grad()
def generator_validity(gen: PlayGenerator, ds: Dataset, n_states: int = 50, per_state: int = 4,
                       seed: int = 0, temperature: float = 1.0) -> dict[str, Any]:
    """Fraction of sampled sequences that detokenise to plays passing the §4.6 validator."""
    rng = np.random.default_rng(seed)
    g = torch.Generator().manual_seed(seed)
    ok = total = 0
    lengths = []
    for i in rng.choice(len(ds), min(n_states, len(ds)), replace=False):
        x = torch.from_numpy(ds.x[i: i + 1].astype(np.float32))
        h = torch.tensor([int(ds.holder[i])])
        for s in gen.sample(x, h, per_state, temperature, g):
            total += 1
            lengths.append(len(s.tokens))
            if s.play is None:
                continue
            try:
                parse_play({**s.play, "id": "probe"})
                ok += 1
            except PlayValidationError:
                pass
    return {"validity": ok / max(total, 1), "sampled": total, "mean_len": float(np.mean(lengths) if lengths else 0)}


def compare_generated_vs_library(ckpt: str | Path, n_episodes: int = 24, workers: int = 4,
                                 seed: int = 11) -> dict[str, Any]:
    """M8 target: generated plays reach >= 80% of the library's mean EPV delta in matched scenarios.

    The same scenarios and seeds are played twice against the same library opponent: once by
    the library policy, once by an agent whose possession plays all come from the generator.
    """
    from ..selfplay.runner import run_jobs
    from ..sim.scenarios import sample_scenario

    rng = np.random.default_rng(seed)
    base = []
    for _ in range(n_episodes):
        sc = sample_scenario(rng, ("mid_progression", "final_third_attack", "transition_win", "random_open_play"))
        base.append({"seed": int(rng.integers(1 << 31)), "scenario": {**sc.to_dict(), "attacking_team": 0},
                     "away": {"id": "library", "kind": "library", "temperature": 0.0}, "randomise": False,
                     "max_time_s": 25.0})
    agent = {"id": "generated_only", "kind": "agent", "checkpoint": str(ckpt), "generator_file": "generator.pt",
             "activation": "always", "k": 4, "critic": False, "generated_only": True, "gen_temperature": 0.8}
    lib = {"id": "library", "kind": "library", "temperature": 0.0}
    means = {}
    for name, home in (("library", lib), ("generated", agent)):
        jobs = [{**b, "episode_id": f"M-{name}-{i}", "home": home} for i, b in enumerate(base)]
        res: list[dict] = []
        run_jobs(jobs, None, workers=workers, on_result=res.append, progress_every=0)
        r = [row["reward"] for x in res for row in x["rows"]
             if row["team"] == 0 and row["phase"] in PHASES and
             (row["chosen_source"] != "library" or name == "library")]
        means[name] = (float(np.mean(r)) if r else 0.0, len(r))
    lm, gm = means["library"][0], means["generated"][0]
    meets = gm >= lm - 0.2 * abs(lm)
    return {"library_mean": lm, "generated_mean": gm, "library_plays": means["library"][1],
            "generated_plays": means["generated"][1], "meets_target": bool(meets)}


def compare_critic_ranking(ckpt: str | Path, n_episodes: int = 60, workers: int = 4, seed: int = 21) -> dict[str, Any]:
    """M7 acceptance: Module 2 with the critic in the score vs without, same games and opponents."""
    from ..selfplay.runner import run_jobs
    from ..sim.scenarios import SCENARIO_TYPES, sample_scenario

    rng = np.random.default_rng(seed)
    base = []
    for _ in range(n_episodes):
        sc = sample_scenario(rng, SCENARIO_TYPES[:-2] + ("random_open_play",))
        base.append({"seed": int(rng.integers(1 << 31)), "scenario": sc.to_dict(),
                     "away": {"id": "library", "kind": "library", "temperature": 0.0}, "randomise": False,
                     "max_time_s": 30.0})
    specs = {
        "without_critic": {"id": "library", "kind": "library", "temperature": 0.0},
        "with_critic": {"id": "critic", "kind": "agent", "checkpoint": str(ckpt), "generator": False,
                        "critic": True, "temperature": 0.0},
    }
    out = {}
    for name, home in specs.items():
        jobs = [{**b, "episode_id": f"C-{name}-{i}", "home": home} for i, b in enumerate(base)]
        res: list[dict] = []
        run_jobs(jobs, None, workers=workers, on_result=res.append, progress_every=0)
        r = [row["reward"] for x in res for row in x["rows"] if row["team"] == 0]
        epv = [row["epv_end"] - row["epv_start"] for x in res for row in x["rows"] if row["team"] == 0]
        out[name] = {"mean_play_reward": float(np.mean(r)), "mean_epv_delta": float(np.mean(epv)),
                     "plays": len(r), "shots": int(sum(x["episode"]["shots_home"] for x in res))}
    out["improves"] = out["with_critic"]["mean_play_reward"] > out["without_critic"]["mean_play_reward"]
    path = Path(ckpt) / "critic_metrics.json"
    if path.exists():
        m = json.loads(path.read_text())
        m["ranking_ab"] = out
        path.write_text(json.dumps(m, indent=2))
    return out
