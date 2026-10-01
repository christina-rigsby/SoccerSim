"""State encoder (spec §10.1).

Nodes: 22 players + ball. Node features: position and velocity (attacking frame,
side-normalised), team flag, side-relative hint one-hot, capabilities, stamina, local
pitch control, xT at position, has_ball. Edges: fully connected, with distance,
relative velocity and same-team flag. The model is a dense GATv2-style message-passing
stack (written directly in PyTorch: a 23-node complete graph needs no sparse library)
that returns node embeddings plus a pooled graph embedding.

:func:`state_features` is NumPy-only so datasets can be built without torch.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from ..dashboard.pitch_control import pitch_control
from ..dashboard.xt import XTSurface, load_xt
from ..schema.vocab import HINTS

N_NODES = 23
HINT_INDEX = {h: i for i, h in enumerate(HINTS)}
KIND_HINT = {"GK": "GK", "DM": "DM", "CM": "CM", "AM": "AM", "ST": "ST"}
# pos, vel, team/ball flags, hint one-hot, capabilities, stamina, pitch control, xT, has_ball
NODE_DIM = 2 + 2 + 2 + len(HINTS) + 13 + 1 + 1 + 1 + 1
EDGE_DIM = 4
_XT: list[XTSurface] = []


def _xt() -> XTSurface:
    if not _XT:
        _XT.append(load_xt())
    return _XT[0]


def _hint(kind: str, base_y: float, side: float) -> str:
    if kind in KIND_HINT:
        return KIND_HINT[kind]
    return f"{kind}_{'near' if base_y * side > 0.5 else 'far'}"


def state_features(state: dict[str, Any], caps: np.ndarray, side: float) -> tuple[np.ndarray, int]:
    """(23, NODE_DIM) node features for a compact dashboard state, plus the ball-holder index.

    Nodes are ordered: our 11 players, their 11, then the ball. Coordinates are already in
    the team's attacking frame; ``side`` mirrors y so "near" is always +y.
    """
    team = int(state["team"])
    order = list(range(team * 11, team * 11 + 11)) + list(range((1 - team) * 11, (2 - team) * 11))
    pos = np.asarray(state["pos"], dtype=np.float32)[order]
    vel = np.asarray(state["vel"], dtype=np.float32)[order]
    pos[:, 1] *= side
    vel[:, 1] *= side
    caps = np.asarray(caps, dtype=np.float32)[order]
    stamina = np.asarray(state["stamina"], dtype=np.float32)[order]
    kinds = [state["kinds"][i] for i in order]
    base_y = np.asarray(state["base_y"], dtype=np.float32)[order]
    # Base positions of the opponents are in their own frame: mirror into ours.
    base_y[11:] *= -1.0
    ball = np.asarray(state["ball"], dtype=np.float32) * np.array([1.0, side], dtype=np.float32)

    vmax = (7.0 + 2.5 * caps[:, 0]) * (0.85 + 0.15 * stamina)
    pc = pitch_control(pos, pos[:11], vel[:11], vmax[:11], pos[11:], vel[11:], vmax[11:])
    xt = _xt().value(pos)
    owner = int(state.get("owner", -1))
    holder = order.index(owner) if owner in order else -1

    x = np.zeros((N_NODES, NODE_DIM), dtype=np.float32)
    x[:22, 0:2] = pos / np.array([52.5, 34.0], dtype=np.float32)
    x[:22, 2:4] = vel / 8.0
    x[:11, 4] = 1.0                       # our team
    x[22, 5] = 1.0                        # ball node
    for i in range(22):
        h = _hint(kinds[i], base_y[i], side)
        x[i, 6 + HINT_INDEX[h]] = 1.0
    off = 6 + len(HINTS)
    x[:22, off:off + 13] = caps
    x[:22, off + 13] = stamina
    x[:22, off + 14] = pc
    x[:22, off + 15] = xt / 0.3
    if holder >= 0:
        x[holder, off + 16] = 1.0
    x[22, 0:2] = ball / np.array([52.5, 34.0], dtype=np.float32)
    bv = np.asarray(state.get("ball_vel", [0.0, 0.0]), dtype=np.float32)
    x[22, 2:4] = bv / 8.0
    x[22, off + 14] = float(pitch_control(ball[None], pos[:11], vel[:11], vmax[:11], pos[11:], vel[11:],
                                          vmax[11:])[0])
    x[22, off + 15] = float(_xt().value(ball)) / 0.3
    return x, (holder if holder >= 0 else 22)


try:  # torch is optional (``pip install .[ml]``)
    import torch
    from torch import nn

    def edge_features(x: torch.Tensor) -> torch.Tensor:
        """(B, N, N, EDGE_DIM) from node features: distance, relative velocity, same-team flag."""
        pos = x[..., 0:2] * torch.tensor([52.5, 34.0], device=x.device)
        vel = x[..., 2:4] * 8.0
        d = torch.cdist(pos, pos) / 50.0
        rv = (vel[:, :, None, :] - vel[:, None, :, :]) / 8.0
        team = x[..., 4]
        same = (team[:, :, None] == team[:, None, :]).float()
        return torch.cat([d[..., None], rv, same[..., None]], dim=-1)

    class GATv2Layer(nn.Module):
        """Dense GATv2: e_ij = a^T LeakyReLU(W_l h_i + W_r h_j + W_e x_ij), multi-head."""

        def __init__(self, dim: int, heads: int) -> None:
            super().__init__()
            self.heads = heads
            self.hd = dim // heads
            self.wl = nn.Linear(dim, dim)
            self.wr = nn.Linear(dim, dim)
            self.we = nn.Linear(EDGE_DIM, dim)
            self.att = nn.Parameter(torch.randn(heads, self.hd) * 0.1)
            self.out = nn.Linear(dim, dim)
            self.norm1 = nn.LayerNorm(dim)
            self.norm2 = nn.LayerNorm(dim)
            self.ff = nn.Sequential(nn.Linear(dim, 2 * dim), nn.GELU(), nn.Linear(2 * dim, dim))

        def forward(self, h: torch.Tensor, e: torch.Tensor) -> torch.Tensor:
            b, n, _ = h.shape
            hl = self.wl(h).view(b, n, self.heads, self.hd)
            hr = self.wr(h).view(b, n, self.heads, self.hd)
            he = self.we(e).view(b, n, n, self.heads, self.hd)
            z = torch.nn.functional.leaky_relu(hl[:, :, None] + hr[:, None, :] + he, 0.2)
            score = (z * self.att).sum(-1)                          # (b, n, n, heads)
            alpha = torch.softmax(score, dim=2)
            msg = torch.einsum("bijh,bjhd->bihd", alpha, hr).reshape(b, n, -1)
            h = self.norm1(h + self.out(msg))
            return self.norm2(h + self.ff(h))

    class StateEncoder(nn.Module):
        def __init__(self, hidden: int = 64, layers: int = 3, heads: int = 4) -> None:
            super().__init__()
            self.inp = nn.Linear(NODE_DIM, hidden)
            self.layers = nn.ModuleList([GATv2Layer(hidden, heads) for _ in range(layers)])
            self.pool = nn.Linear(2 * hidden, hidden)
            self.hidden = hidden

        def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
            """``x``: (B, 23, NODE_DIM) -> node embeddings (B, 23, H), graph embedding (B, H)."""
            e = edge_features(x)
            h = self.inp(x)
            for layer in self.layers:
                h = layer(h, e)
            g = self.pool(torch.cat([h.mean(1), h.max(1).values], dim=-1))
            return h, g

except ImportError:  # pragma: no cover
    torch = None
