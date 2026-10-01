"""Turning self-play logs into tensors for the critic, the response model and BC (spec §11)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..schema.models import Play
from ..schema.validate import parse_play
from ..selfplay.logging import load_table
from .critic import OUTCOME_EVENTS
from .encoder import NODE_DIM, state_features
from .grammar import BOS, EOS, PAD
from .tokenizer import TokenizeError, tokenize_library, tokenize_play

SUCCESS = ("success", "completed")


def play_ids(library: dict[str, Play]) -> list[str]:
    return sorted(library) + ["generated"]


def opp_classes(library: dict[str, Play]) -> list[str]:
    return sorted(library) + ["generated", "none"]


@dataclass
class Dataset:
    x: np.ndarray            # (N, 23, F) float16
    holder: np.ndarray       # (N,) int16
    tokens: np.ndarray       # (N, L) int16
    ident: np.ndarray        # (N,) int16
    reward: np.ndarray       # (N,) float32
    success: np.ndarray      # (N,) float32
    opp: np.ndarray          # (N,) int16
    events: np.ndarray       # (N, E) float32
    episode: np.ndarray      # (N,) object
    chosen: np.ndarray       # (N,) object
    phase: np.ndarray        # (N,) object
    team: np.ndarray         # (N,) int8
    t: np.ndarray            # (N,) float32

    def __len__(self) -> int:
        return len(self.reward)

    def subset(self, idx: np.ndarray) -> Dataset:
        return Dataset(**{k: getattr(self, k)[idx] for k in self.__dataclass_fields__})

    def split(self, frac: float = 0.1, seed: int = 0) -> tuple[Dataset, Dataset]:
        eps = np.unique(self.episode)
        rng = np.random.default_rng(seed)
        held = set(rng.choice(eps, max(1, int(len(eps) * frac)), replace=False))
        mask = np.array([e in held for e in self.episode])
        return self.subset(np.where(~mask)[0]), self.subset(np.where(mask)[0])


def row_tokens(row: dict, lib_tokens: dict[str, list[int]]) -> list[int]:
    if row["chosen_source"] == "library":
        return lib_tokens.get(row["chosen"], [])
    if row.get("chosen_tokens"):
        return json.loads(row["chosen_tokens"])
    if row.get("play_json"):
        try:
            return tokenize_play(parse_play(json.loads(row["play_json"])))
        except (TokenizeError, ValueError):
            return []
    return []


def build_dataset(root: str | Path, library: dict[str, Play], max_rows: int | None = None, seed: int = 0,
                  recycle_share: float = 0.35, max_len: int = 256) -> Dataset:
    cols = ["episode_id", "t", "team", "state", "side", "chosen", "chosen_source", "chosen_tokens", "play_json",
            "reward", "end_reason", "opp_play_at_end", "events", "phase"]
    rows = load_table(root, "decisions", cols).to_pylist()
    eps = {e["episode_id"]: np.asarray(json.loads(e["caps"]), dtype=np.float32)
           for e in load_table(root, "episodes", ["episode_id", "caps"]).to_pylist()}
    rng = np.random.default_rng(seed)
    rows = [r for r in rows if r["state"] and r["state"] != "null" and r["episode_id"] in eps]
    # Rebalance: the fallback play dominates raw logs.
    rec = [i for i, r in enumerate(rows) if r["chosen"] == "recycle_possession"]
    other = [i for i, r in enumerate(rows) if r["chosen"] != "recycle_possession"]
    keep_rec = int(min(len(rec), recycle_share / (1 - recycle_share) * len(other)))
    idx = other + list(rng.choice(rec, keep_rec, replace=False)) if rec else other
    rng.shuffle(idx)
    if max_rows:
        idx = idx[:max_rows]
    lib_tok = tokenize_library(library)
    ids = {p: i for i, p in enumerate(play_ids(library))}
    oc = {p: i for i, p in enumerate(opp_classes(library))}
    n = len(idx)
    x = np.zeros((n, 23, NODE_DIM), dtype=np.float16)
    holder = np.zeros(n, dtype=np.int16)
    toks = np.full((n, max_len), PAD, dtype=np.int16)
    out = {k: [] for k in ("ident", "reward", "success", "opp", "events", "episode", "chosen", "phase", "team", "t")}
    for k, i in enumerate(idx):
        r = rows[i]
        st = json.loads(r["state"])
        feats, h = state_features(st, eps[r["episode_id"]], float(r["side"] or 1.0))
        x[k] = feats
        holder[k] = h
        # Untokenizable (defensive) plays are represented by BOS EOS plus their identity embedding.
        tk = row_tokens(r, lib_tok)[:max_len] or [BOS, EOS]
        toks[k, : len(tk)] = tk
        out["ident"].append(ids.get(r["chosen"], ids["generated"]) if r["chosen_source"] == "library"
                            else ids["generated"])
        out["reward"].append(r["reward"])
        out["success"].append(float(r["end_reason"] in SUCCESS))
        opp = r["opp_play_at_end"] or "none"
        out["opp"].append(oc.get(opp, oc["generated"]))
        evs = np.zeros(len(OUTCOME_EVENTS), dtype=np.float32)
        for e in json.loads(r["events"]):
            if e["type"] in OUTCOME_EVENTS and (e["team"] is None or e["team"] == r["team"]):
                evs[OUTCOME_EVENTS.index(e["type"])] = 1.0
        out["events"].append(evs)
        out["episode"].append(r["episode_id"])
        out["chosen"].append(r["chosen"])
        out["phase"].append(r["phase"])
        out["team"].append(r["team"])
        out["t"].append(r["t"])
    return Dataset(
        x=x, holder=holder, tokens=toks, ident=np.array(out["ident"], dtype=np.int16),
        reward=np.array(out["reward"], dtype=np.float32), success=np.array(out["success"], dtype=np.float32),
        opp=np.array(out["opp"], dtype=np.int16), events=np.stack(out["events"]) if n else np.zeros((0, 8)),
        episode=np.array(out["episode"], dtype=object), chosen=np.array(out["chosen"], dtype=object),
        phase=np.array(out["phase"], dtype=object), team=np.array(out["team"], dtype=np.int8),
        t=np.array(out["t"], dtype=np.float32),
    )
