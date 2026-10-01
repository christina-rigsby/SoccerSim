"""PPO over token sequences for the generator (spec §11 Phase C.2).

Reward = realised play-level EPV delta (plus terminal goal +-1, already in the play
reward); advantage = reward - critic baseline; a KL penalty to the frozen Phase B
generator keeps the policy from drifting into simulator exploits and gibberish.
Log-probabilities are grammar-masked, exactly as during sampling. The clipped ratio is
taken per token (the sequence advantage is shared by its tokens): a whole-sequence ratio
over ~100 tokens moves by orders of magnitude after a single step and clips everything.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import torch

from .critic import Critic
from .model import PlayGenerator, grammar_masks, pad_batch


@torch.no_grad()
def critic_baseline(critic: Critic | None, rollouts: list[dict], generated_ident: int) -> np.ndarray:
    if critic is None or not rollouts:
        return np.zeros(len(rollouts), dtype=np.float32)
    x = torch.from_numpy(np.stack([r["x"] for r in rollouts]).astype(np.float32))
    h = torch.tensor([r["holder"] for r in rollouts])
    tk = pad_batch([r["tokens"] for r in rollouts], 256)
    ident = torch.full((len(rollouts),), generated_ident, dtype=torch.long)
    v, _ = critic.value(x, h, tk, ident)
    return v.numpy()


def ppo_update(gen: PlayGenerator, ref: PlayGenerator, rollouts: list[dict[str, Any]], baseline: np.ndarray,
               cfg: dict, opt: torch.optim.Optimizer, batch: int = 32) -> dict[str, float]:
    if len(rollouts) < 2:
        return {"n": len(rollouts), "skipped": 1.0}
    # Dropout off: the ratio must compare the same deterministic policy that sampled.
    gen.eval()
    rewards = np.array([r["reward"] for r in rollouts], dtype=np.float32)
    adv = rewards - baseline
    adv = (adv - adv.mean()) / (adv.std() + 1e-6)
    seqs = [r["tokens"] for r in rollouts]
    masks = [grammar_masks(s) for s in seqs]
    x_all = torch.from_numpy(np.stack([r["x"] for r in rollouts]).astype(np.float32))
    h_all = torch.tensor([r["holder"] for r in rollouts])

    def batched(model, fn):
        outs = []
        for i in range(0, len(seqs), batch):
            sl = slice(i, i + batch)
            lp, valid = model.token_logprobs(x_all[sl], h_all[sl], pad_batch(seqs[sl], L), masks[sl])
            outs.append(fn(lp, valid))
        return torch.cat(outs)

    L = max(len(s) for s in seqs)
    with torch.no_grad():
        old_tok = batched(gen, lambda lp, v: lp)
        ref_tok = batched(ref, lambda lp, v: lp)
    A = torch.from_numpy(adv)
    stats = {"loss": 0.0, "kl_ref": 0.0, "clipfrac": 0.0, "ratio": 0.0}
    steps = 0
    rng = np.random.default_rng(0)
    for _ in range(cfg["epochs"]):
        perm = rng.permutation(len(seqs))
        for i in range(0, len(seqs), batch):
            idx = perm[i:i + batch]
            tk = pad_batch([seqs[j] for j in idx], L)
            lp, valid = gen.token_logprobs(x_all[idx], h_all[idx], tk, [masks[j] for j in idx])
            n_tok = valid.sum().clamp(min=1.0)
            ratio = torch.exp(torch.clamp(lp - old_tok[idx], -20, 20))
            a = A[idx][:, None]
            surr = torch.min(ratio * a, torch.clamp(ratio, 1 - cfg["clip"], 1 + cfg["clip"]) * a)
            pg = -(surr * valid).sum() / n_tok
            kl = ((lp - ref_tok[idx]) * valid).sum() / n_tok
            loss = pg + cfg["kl_beta"] * kl
            opt.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(gen.parameters(), 1.0)
            opt.step()
            with torch.no_grad():
                stats["loss"] += loss.item()
                stats["kl_ref"] += kl.item()
                stats["clipfrac"] += (((ratio - 1).abs() > cfg["clip"]).float() * valid).sum().item() / n_tok.item()
                stats["ratio"] += ((ratio * valid).sum() / n_tok).item()
            steps += 1
    gen.eval()
    out = {k: v / max(steps, 1) for k, v in stats.items()}
    out.update(n=len(rollouts), mean_reward=float(rewards.mean()), mean_adv_raw=float((rewards - baseline).mean()))
    return out
