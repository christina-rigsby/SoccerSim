"""Critic Q(state, play) -> {epv_delta_mean, success_prob} (spec §10.4) and the response
model R(state, play) -> opponent's next play + outcome events (spec §10.5).

Both read the state through the GNN encoder and the play through a transformer encoder
over its tokens, plus a learned embedding of the play's identity (each library play, or
"generated"). Defensive library plays are not tokenizable, so for them the identity
embedding carries the play; generated plays are represented by their tokens.
"""

from __future__ import annotations

import torch
from torch import nn

from .encoder import StateEncoder
from .grammar import PAD, VOCAB_SIZE

OUTCOME_EVENTS = ("shot_taken", "goal", "goal_conceded", "possession_lost", "possession_won", "pass_completed",
                  "pass_intercepted", "ball_out")


class PlayEncoder(nn.Module):
    def __init__(self, n_ids: int, d: int = 64, layers: int = 2, heads: int = 4, max_len: int = 321) -> None:
        super().__init__()
        self.tok = nn.Embedding(VOCAB_SIZE, d, padding_idx=PAD)
        self.pos = nn.Embedding(max_len, d)
        self.ident = nn.Embedding(n_ids, d)
        layer = nn.TransformerEncoderLayer(d, heads, 4 * d, dropout=0.1, batch_first=True, norm_first=True)
        self.enc = nn.TransformerEncoder(layer, layers, enable_nested_tensor=False)
        self.d = d

    def forward(self, tokens: torch.Tensor, ident: torch.Tensor) -> torch.Tensor:
        # Batches are dominated by a handful of distinct plays: encode each distinct token
        # sequence once and scatter the result back.
        uniq, inv = torch.unique(tokens, dim=0, return_inverse=True)
        return self._encode(uniq)[inv] + self.ident(ident)

    def _encode(self, tokens: torch.Tensor) -> torch.Tensor:
        L = tokens.shape[1]
        h = self.tok(tokens) + self.pos(torch.arange(L, device=tokens.device))[None]
        pad = tokens == PAD
        h = self.enc(h, src_key_padding_mask=pad)
        keep = (~pad).float()[..., None]
        return (h * keep).sum(1) / keep.sum(1).clamp(min=1.0)


class _StatePlayNet(nn.Module):
    def __init__(self, n_ids: int, enc: dict, d: int, layers: int, heads: int, out: int) -> None:
        super().__init__()
        self.config = {"n_ids": n_ids, "enc": enc, "d": d, "layers": layers, "heads": heads}
        self.state = StateEncoder(**enc)
        self.play = PlayEncoder(n_ids, d, layers, heads)
        h = enc["hidden"]
        self.mlp = nn.Sequential(nn.Linear(2 * h + d, 2 * d), nn.GELU(), nn.Linear(2 * d, d), nn.GELU(),
                                 nn.Linear(d, out))

    def trunk(self, x, holder, tokens, ident):
        nodes, g = self.state(x)
        hold = nodes[torch.arange(len(x)), holder]
        return self.mlp(torch.cat([g, hold, self.play(tokens, ident)], dim=-1))


class Critic(_StatePlayNet):
    """Outputs (normalised epv_delta, success logit)."""

    def __init__(self, n_ids: int, enc: dict | None = None, d: int = 64, layers: int = 2, heads: int = 4) -> None:
        super().__init__(n_ids, enc or {"hidden": 64, "layers": 3, "heads": 4}, d, layers, heads, 2)
        self.register_buffer("y_mean", torch.zeros(()))
        self.register_buffer("y_std", torch.ones(()))

    def forward(self, x, holder, tokens, ident):
        o = self.trunk(x, holder, tokens, ident)
        return o[:, 0], o[:, 1]

    def value(self, x, holder, tokens, ident) -> tuple[torch.Tensor, torch.Tensor]:
        """EPV-delta prediction in EPV units and success probability."""
        v, s = self.forward(x, holder, tokens, ident)
        return v * self.y_std + self.y_mean, torch.sigmoid(s)


class ResponseModel(_StatePlayNet):
    """Outputs (logits over opponent's next play id, logits over outcome events)."""

    def __init__(self, n_ids: int, n_opp: int, enc: dict | None = None, d: int = 64, layers: int = 2,
                 heads: int = 4) -> None:
        super().__init__(n_ids, enc or {"hidden": 64, "layers": 3, "heads": 4}, d, layers, heads,
                         n_opp + len(OUTCOME_EVENTS))
        self.n_opp = n_opp
        self.config["n_opp"] = n_opp

    def forward(self, x, holder, tokens, ident):
        o = self.trunk(x, holder, tokens, ident)
        return o[:, : self.n_opp], o[:, self.n_opp:]
