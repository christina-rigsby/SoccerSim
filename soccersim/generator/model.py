"""Generator (spec §10.3): a transformer decoder over play tokens, cross-attending to the
GNN state encoding (graph embedding, ball-holder node, and every node).

Decoding is grammar-constrained: at each step the logits are masked to the tokens the
grammar program allows, so every sampled sequence detokenises to a schema-valid play.
The interface stays generic — ``sample(features, holder, n)`` — so a diffusion model
can replace it later (spec §16.3).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import torch
from torch import nn

from .encoder import StateEncoder
from .grammar import BOS, EOS, PAD, VOCAB_SIZE, play_program


def grammar_masks(tokens: list[int], max_len: int = 320) -> np.ndarray:
    """(len(tokens) - 1, V) boolean masks: allowed next tokens at each position."""
    prog = play_program(max_len)
    allowed = next(prog)
    masks = []
    try:
        for t in tokens:
            if t == BOS and not masks and allowed == frozenset({BOS}):
                allowed = prog.send(t)
                continue
            m = np.zeros(VOCAB_SIZE, dtype=bool)
            m[list(allowed)] = True
            masks.append(m)
            allowed = prog.send(t)
    except StopIteration:
        pass
    return np.stack(masks) if masks else np.zeros((0, VOCAB_SIZE), dtype=bool)


@dataclass
class Sample:
    tokens: list[int]
    logprob: float
    play: dict | None


class PlayGenerator(nn.Module):
    def __init__(self, enc: dict | None = None, d_model: int = 128, layers: int = 3, heads: int = 4,
                 max_len: int = 320) -> None:
        super().__init__()
        enc = enc or {"hidden": 64, "layers": 3, "heads": 4}
        self.config = {"enc": enc, "d_model": d_model, "layers": layers, "heads": heads, "max_len": max_len}
        self.encoder = StateEncoder(**enc)
        self.mem_proj = nn.Linear(enc["hidden"], d_model)
        self.tok = nn.Embedding(VOCAB_SIZE, d_model, padding_idx=PAD)
        self.pos = nn.Embedding(max_len + 1, d_model)
        layer = nn.TransformerDecoderLayer(d_model, heads, 4 * d_model, dropout=0.1, batch_first=True,
                                           norm_first=True)
        self.dec = nn.TransformerDecoder(layer, layers)
        self.head = nn.Linear(d_model, VOCAB_SIZE)
        self.max_len = max_len

    def memory(self, x: torch.Tensor, holder: torch.Tensor) -> torch.Tensor:
        nodes, g = self.encoder(x)
        hold = nodes[torch.arange(len(x)), holder]
        return self.mem_proj(torch.cat([g[:, None], hold[:, None], nodes], dim=1))

    def logits(self, mem: torch.Tensor, inp: torch.Tensor) -> torch.Tensor:
        L = inp.shape[1]
        h = self.tok(inp) + self.pos(torch.arange(L, device=inp.device))[None]
        causal = torch.triu(torch.ones((L, L), dtype=torch.bool, device=inp.device), diagonal=1)
        out = self.dec(h, mem, tgt_mask=causal, tgt_key_padding_mask=inp == PAD)
        return self.head(out)

    def forward(self, x, holder, tokens):
        """Teacher-forced logits for predicting ``tokens[:, 1:]``."""
        return self.logits(self.memory(x, holder), tokens[:, :-1])

    def sequence_logprob(self, x, holder, tokens: torch.Tensor, masks: list[np.ndarray] | None = None):
        """Sum of (grammar-masked) log-probabilities of each sequence's tokens after BOS."""
        lp, valid = self.token_logprobs(x, holder, tokens, masks)
        return (lp * valid).sum(-1)

    def token_logprobs(self, x, holder, tokens: torch.Tensor, masks: list[np.ndarray] | None = None):
        """Per-token (grammar-masked) log-probabilities ``(B, L-1)`` and the valid-token mask."""
        logits = self.forward(x, holder, tokens)
        if masks is not None:
            m = torch.zeros_like(logits, dtype=torch.bool)
            for i, mk in enumerate(masks):
                m[i, : len(mk)] = torch.from_numpy(mk)
            logits = logits.masked_fill(~m, -1e9)
        logp = torch.log_softmax(logits, dim=-1)
        tgt = tokens[:, 1:]
        lp = logp.gather(-1, tgt.clamp(min=0)[..., None])[..., 0]
        return lp, (tgt != PAD).float()

    @torch.no_grad()
    def sample(self, x: torch.Tensor, holder: torch.Tensor, n: int, temperature: float = 1.0,
               gen: torch.Generator | None = None) -> list[Sample]:
        """Sample ``n`` grammar-valid sequences for one state (``x``: (1, 23, F))."""
        mem = self.memory(x, holder).expand(n, -1, -1)
        progs = [play_program(self.max_len) for _ in range(n)]
        allowed = [next(p) for p in progs]
        seqs = [[BOS] for _ in range(n)]
        for i, p in enumerate(progs):
            allowed[i] = p.send(BOS)
        logps = [0.0] * n
        plays: list[dict | None] = [None] * n
        done = [False] * n
        for _ in range(self.max_len):
            live = [i for i in range(n) if not done[i]]
            if not live:
                break
            L = max(len(seqs[i]) for i in live)
            inp = torch.full((len(live), L), PAD, dtype=torch.long)
            for r, i in enumerate(live):
                inp[r, : len(seqs[i])] = torch.tensor(seqs[i])
            lg = self.logits(mem[live], inp)
            for r, i in enumerate(live):
                row = lg[r, len(seqs[i]) - 1] / max(temperature, 1e-3)
                mask = torch.full_like(row, float("-inf"))
                mask[list(allowed[i])] = 0.0
                logp = torch.log_softmax(row + mask, dim=-1)
                t = int(torch.multinomial(logp.exp(), 1, generator=gen)) if temperature > 0 else int(logp.argmax())
                logps[i] += float(logp[t])
                seqs[i].append(t)
                try:
                    allowed[i] = progs[i].send(t)
                except StopIteration as stop:
                    plays[i] = stop.value
                    done[i] = True
        return [Sample(seqs[i], logps[i], plays[i]) for i in range(n)]


def pad_batch(seqs: list[list[int]], max_len: int | None = None) -> torch.Tensor:
    L = max(len(s) for s in seqs) if max_len is None else max_len
    out = torch.full((len(seqs), L), PAD, dtype=torch.long)
    for i, s in enumerate(seqs):
        out[i, : min(len(s), L)] = torch.tensor(s[:L])
    return out


__all__ = ["EOS", "PlayGenerator", "Sample", "grammar_masks", "pad_batch"]
