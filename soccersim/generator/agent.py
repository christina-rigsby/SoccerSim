"""The learning agent: Module 2 ranking with the critic in the score and the generator in
the candidate set (spec §10–11).

Models are loaded from a checkpoint directory written by :mod:`.train`:
``critic.pt``, ``response.pt``, ``generator.pt`` (plus league copies) and ``meta.json``.
Every generated play the agent *chooses* is recorded with its tokens, log-probability and
state features, so the worker can hand PPO a rollout once rewards are known.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import torch

from ..dashboard.team_state import TeamView
from ..ranking.selector import RankingPolicy
from ..schema.models import Play
from ..schema.validate import PlayValidationError, parse_play
from .critic import OUTCOME_EVENTS, Critic, ResponseModel
from .data import opp_classes, play_ids
from .encoder import state_features
from .grammar import BOS, EOS, play_id_for
from .model import PlayGenerator, pad_batch
from .tokenizer import TokenizeError, tokenize_library, tokenize_play

POSSESSION = ("in_possession", "transition_attack", "set_piece")


def save_model(model: torch.nn.Module, path: str | Path, **extra: Any) -> None:
    torch.save({"config": model.config, "state": model.state_dict(), **extra}, path)


def load_generator(path: str | Path) -> PlayGenerator:
    ck = torch.load(path, map_location="cpu", weights_only=False)
    c = ck["config"]
    g = PlayGenerator(c["enc"], c["d_model"], c["layers"], c["heads"], c["max_len"])
    g.load_state_dict(ck["state"])
    g.eval()
    return g


def load_critic(path: str | Path) -> Critic:
    ck = torch.load(path, map_location="cpu", weights_only=False)
    c = ck["config"]
    m = Critic(c["n_ids"], c["enc"], c["d"], c["layers"], c["heads"])
    m.load_state_dict(ck["state"])
    m.eval()
    return m


def load_response(path: str | Path) -> ResponseModel:
    ck = torch.load(path, map_location="cpu", weights_only=False)
    c = ck["config"]
    m = ResponseModel(c["n_ids"], c["n_opp"], c["enc"], c["d"], c["layers"], c["heads"])
    m.load_state_dict(ck["state"])
    m.eval()
    return m


class Bundle:
    """Models + vocabularies shared by every agent in a process."""

    def __init__(self, ckpt: str | Path, library: dict[str, Play], generator_file: str = "generator.pt") -> None:
        self.dir = Path(ckpt)
        self.library = library
        self.ids = {p: i for i, p in enumerate(play_ids(library))}
        self.opp = opp_classes(library)
        self.lib_tokens = tokenize_library(library)
        self.critic = load_critic(self.dir / "critic.pt") if (self.dir / "critic.pt").exists() else None
        self.response = load_response(self.dir / "response.pt") if (self.dir / "response.pt").exists() else None
        gpath = self.dir / generator_file
        self.generator = load_generator(gpath) if gpath.exists() else None
        self.gen_tokens: dict[str, list[int]] = {}

    def play_tokens(self, play: Play) -> list[int]:
        if play.source == "library":
            return self.lib_tokens.get(play.id, [])
        if play.id in self.gen_tokens:
            return self.gen_tokens[play.id]
        try:
            return tokenize_play(play)
        except TokenizeError:
            return []


@lru_cache(maxsize=8)
def _bundle(ckpt: str, generator_file: str, lib_key: int) -> Bundle:
    from ..schema import load_library

    return Bundle(ckpt, load_library(), generator_file)


class _StateCache:
    def __init__(self) -> None:
        self.key = None
        self.x: torch.Tensor | None = None
        self.holder: torch.Tensor | None = None

    def get(self, view: TeamView, side: float):
        key = (id(view.state), view.tick, view.team, side)
        if key != self.key:
            st = view.compact()
            feats, h = state_features(st, view.state.caps, side)
            self.x = torch.from_numpy(feats)[None]
            self.holder = torch.tensor([h])
            self.key = key
        return self.x, self.holder


class CriticFn:
    """``critic(view, play, binding) -> EPV`` for the ranking score (plus optional lookahead)."""

    def __init__(self, bundle: Bundle, lookahead: bool = False, gamma: float = 0.5) -> None:
        self.b = bundle
        self.cache = _StateCache()
        self.lookahead = lookahead and bundle.response is not None
        self.gamma = gamma
        self.last: dict[str, dict[str, float]] = {}

    def __call__(self, view: TeamView, play: Play, binding: dict) -> float:
        if self.b.critic is None:
            return 0.0
        x, h = self.cache.get(view, view.side_from_ball())
        toks = pad_batch([self.b.play_tokens(play) or [BOS, EOS]])
        ident = torch.tensor([self.b.ids.get(play.id, self.b.ids["generated"]) if play.source == "library"
                              else self.b.ids["generated"]])
        with torch.no_grad():
            v, s = self.b.critic.value(x, h, toks, ident)
            val = float(v[0])
            info = {"value": val, "success_p": float(s[0])}
            if self.lookahead:
                _, ev = self.b.response(x, h, toks, ident)
                p = torch.sigmoid(ev[0]).numpy()
                e = dict(zip(OUTCOME_EVENTS, p, strict=True))
                # One-step lookahead (spec §10.5), approximated by the value of the predicted
                # outcome events rather than a second critic call per opponent response.
                look = e["goal"] - e["goal_conceded"] + 0.05 * e["shot_taken"] - 0.02 * e["possession_lost"]
                val += self.gamma * float(look)
                info["lookahead"] = float(look)
        self.last[play.id] = info
        return val

    def predict_opponent(self, view: TeamView, play: Play) -> dict[str, float]:
        """Opponent model v2 (spec §8.2): distribution over the opponent's next play."""
        if self.b.response is None:
            return {}
        x, h = self.cache.get(view, view.side_from_ball())
        toks = pad_batch([self.b.play_tokens(play) or [BOS, EOS]])
        ident = torch.tensor([self.b.ids.get(play.id, self.b.ids["generated"])])
        with torch.no_grad():
            logits, _ = self.b.response(x, h, toks, ident)
        p = torch.softmax(logits[0], -1).numpy()
        return {c: float(v) for c, v in zip(self.b.opp, p, strict=True) if v > 0.02}


class TorchGenerator:
    """``Generator.sample(obs, n) -> list[Play]`` backed by :class:`PlayGenerator`."""

    def __init__(self, bundle: Bundle, rng: np.random.Generator, temperature: float = 1.0) -> None:
        self.b = bundle
        self.temperature = temperature
        self.gen = torch.Generator().manual_seed(int(rng.integers(1 << 31)))
        self.cache = _StateCache()
        self.last: dict[str, dict[str, Any]] = {}
        self.stats = {"sampled": 0, "valid": 0}

    def sample(self, obs: TeamView, n: int) -> list[Play]:
        if self.b.generator is None or obs.holder < 0:
            return []
        side = obs.side_from_ball()
        x, h = self.cache.get(obs, side)
        samples = self.b.generator.sample(x, h, n, self.temperature, self.gen)
        plays, seen = [], set()
        self.last = {}
        for s in samples:
            self.stats["sampled"] += 1
            if s.play is None:
                continue
            pid = play_id_for(s.tokens)
            d = dict(s.play, id=pid)
            try:
                play = parse_play(d)
            except PlayValidationError:
                continue
            self.stats["valid"] += 1
            self.b.gen_tokens[pid] = s.tokens
            self.last[pid] = {"tokens": s.tokens, "logprob": s.logprob, "x": x[0].numpy().astype(np.float16),
                              "holder": int(h[0])}
            if pid not in seen:
                seen.add(pid)
                plays.append(play)
        return plays


class AgentPolicy(RankingPolicy):
    def __init__(self, library, bundle: Bundle, rng, spec: dict[str, Any]) -> None:
        super().__init__(library, rng=rng, temperature=spec.get("temperature", 0.0), name=spec.get("id", "agent"))
        cfg = self.cfg
        self.bundle = bundle
        self.critic_fn = CriticFn(bundle, spec.get("lookahead", False)) if spec.get("critic", True) else None
        self.critic = self.critic_fn
        cfg["critic"]["enabled"] = self.critic_fn is not None and bundle.critic is not None
        cfg["critic"]["weight"] = spec.get("critic_weight", 1.0)
        gen_on = spec.get("generator", True) and bundle.generator is not None
        cfg["generator"]["enabled"] = gen_on
        cfg["generator"]["activation"] = spec.get("activation", cfg["generator"]["activation"])
        cfg["generator"]["k"] = spec.get("k", cfg["generator"]["k"])
        if "threshold" in spec:
            cfg["generator"]["threshold"] = spec["threshold"]
        self.generator = TorchGenerator(bundle, rng, spec.get("gen_temperature", 1.0)) if gen_on else None
        self.rollout_buffer: list[dict[str, Any]] = []
        # Evaluation mode: the generator replaces the library's possession plays entirely.
        self.generated_only = bool(spec.get("generated_only", False))

    def rank(self, obs: TeamView, plays: list[Play]):
        if self.generated_only:
            plays = [p for p in plays if p.source != "library" or p.phase not in POSSESSION]
        return super().rank(obs, plays)

    def decide(self, obs: TeamView, reason: str):
        inst = super().decide(obs, reason)
        if inst is not None and inst.play.source == "generated" and self.generator is not None:
            info = self.generator.last.get(inst.play.id)
            if info is not None:
                self.rollout_buffer.append({"decision_id": inst.decision_id, "play_id": inst.play.id,
                                            "team": obs.team, "t": obs.t, **info})
        if self.last_decision is not None and self.critic_fn is not None:
            for c in self.last_decision["candidates"]:
                info = self.critic_fn.last.get(c["play_id"])
                if info:
                    c["critic"] = round(info["value"], 5)
        return inst

    def finalize(self, plays: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Attach realised rewards to recorded rollouts and tokens to play records."""
        by_dec = {(p.get("decision") or {}).get("decision_id"): p for p in plays}
        out = []
        for r in self.rollout_buffer:
            rec = by_dec.get(r["decision_id"])
            if rec is None or "reward" not in rec:
                continue
            out.append({**r, "reward": rec["reward"], "return": rec.get("return", rec["reward"]),
                        "end_reason": rec["end_reason"], "steps": rec["steps_visited"]})
        return out


def make_agent_policy(spec: dict[str, Any], library: dict[str, Play], rng: np.random.Generator) -> AgentPolicy:
    torch.set_num_threads(1)
    bundle = _bundle(str(spec["checkpoint"]), spec.get("generator_file", "generator.pt"), len(library))
    return AgentPolicy(library, bundle, rng, spec)


def load_meta(ckpt: str | Path) -> dict[str, Any]:
    p = Path(ckpt) / "meta.json"
    return json.loads(p.read_text()) if p.exists() else {}
