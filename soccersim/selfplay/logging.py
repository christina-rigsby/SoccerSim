"""Self-play logs (spec §13): one Parquet row per decision, plus per-episode rows and
optional 10 Hz tracking files for the replay viewer.

Nested fields (state, candidates, events, binding) are stored as JSON strings, which
keeps the schema flat and stable while plays and dashboards evolve.
"""

from __future__ import annotations

import gzip
import json
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from ..schema.models import Play
from ..sim.env import EpisodeResult
from .rewards import assign_rewards

DECISION_SCHEMA = pa.schema([
    ("episode_id", pa.string()), ("t", pa.float32()), ("team", pa.int8()), ("reason", pa.string()),
    ("state", pa.string()), ("candidates", pa.string()),
    ("chosen", pa.string()), ("chosen_source", pa.string()), ("chosen_tokens", pa.string()),
    ("binding", pa.string()), ("side", pa.float32()), ("score", pa.float32()),
    ("generator_used", pa.bool_()), ("library_gap", pa.bool_()),
    ("opp_active_play", pa.string()), ("opp_play_at_end", pa.string()),
    ("events", pa.string()), ("end_reason", pa.string()), ("duration_s", pa.float32()),
    ("epv_start", pa.float32()), ("epv_end", pa.float32()), ("reward", pa.float32()), ("return", pa.float32()),
    ("phase", pa.string()), ("objective", pa.string()), ("play_json", pa.string()),
    ("sim_config_hash", pa.string()), ("policy_checkpoint", pa.string()), ("opponent_id", pa.string()),
    ("scenario", pa.string()),
])

EPISODE_SCHEMA = pa.schema([
    ("episode_id", pa.string()), ("seed", pa.int64()), ("scenario", pa.string()), ("home", pa.string()),
    ("away", pa.string()), ("score_home", pa.int8()), ("score_away", pa.int8()), ("end_cause", pa.string()),
    ("duration_s", pa.float32()), ("caps", pa.string()), ("kinds", pa.string()), ("xt_moves", pa.string()),
    ("xt_shots", pa.string()), ("shots_home", pa.int16()), ("shots_away", pa.int16()),
    ("goals_home", pa.int16()), ("goals_away", pa.int16()),
    ("sim_config_hash", pa.string()),
])


def xt_transitions(res: EpisodeResult, every: int = 10) -> tuple[list, list]:
    """Moves (1 s ball-progression samples) and shots, in the attacking team's frame."""
    moves = []
    fr = res.frames
    for a, b in zip(fr[::every], fr[every::every], strict=False):
        team = a["poss"]
        if team is None or a["o"] < 0:
            continue
        d = 1.0 if team == 0 else -1.0
        ok = b["poss"] == team
        moves.append([round(d * a["b"][0], 1), round(d * a["b"][1], 1), round(d * b["b"][0], 1),
                      round(d * b["b"][1], 1), int(ok)])
    shots = []
    for e in res.events:
        if e["type"] == "shot_taken":
            fp = e.get("data", {}).get("frame_pos") or e["pos"]
            shots.append([fp[0], fp[1], int(e.get("data", {}).get("outcome") == "goal")])
    return moves, shots


def episode_rows(res: EpisodeResult, episode_id: str, library: dict[str, Play], home_id: str, away_id: str,
                 checkpoint: str = "", training_cfg: dict | None = None) -> tuple[list[dict], dict]:
    phases = {pid: p.phase for pid, p in library.items()}
    objectives = {pid: p.objective for pid, p in library.items()}
    for rec in res.plays:
        if rec.get("play_yaml"):
            phases[rec["play_id"]] = rec["play_yaml"]["phase"]
            objectives[rec["play_id"]] = rec["play_yaml"]["objective"]
    assign_rewards(res.plays, phases, objectives, training_cfg)
    rows = []
    for rec in res.plays:
        dec = rec.get("decision") or {}
        team = rec["team"]
        rows.append({
            "episode_id": episode_id, "t": rec["t_start"], "team": team, "reason": dec.get("reason", ""),
            "state": json.dumps(rec.get("state")), "candidates": json.dumps(dec.get("candidates", [])),
            "chosen": rec["play_id"], "chosen_source": rec["source"],
            "chosen_tokens": json.dumps(rec.get("tokens")) if rec.get("tokens") else "",
            "binding": json.dumps(rec["binding"]), "side": rec["side"], "score": rec.get("score", 0.0),
            "generator_used": bool(dec.get("generator_used")), "library_gap": bool(dec.get("library_gap")),
            "opp_active_play": rec.get("opp_play_at_start") or "", "opp_play_at_end": rec.get("opp_play_at_end") or "",
            "events": json.dumps(rec.get("events", [])), "end_reason": rec["end_reason"],
            "duration_s": rec["duration_s"], "epv_start": rec.get("epv_start") or 0.0,
            "epv_end": rec.get("epv_end") if rec.get("epv_end") is not None else rec.get("epv_start") or 0.0,
            "reward": rec["reward"], "return": rec["return"],
            "phase": phases.get(rec["play_id"], ""), "objective": objectives.get(rec["play_id"], ""),
            "play_json": json.dumps(rec["play_yaml"]) if rec.get("play_yaml") else "",
            "sim_config_hash": res.sim_config_hash, "policy_checkpoint": checkpoint,
            "opponent_id": away_id if team == 0 else home_id, "scenario": json.dumps(res.scenario),
        })
    moves, shots = xt_transitions(res) if res.frames else ([], [])
    ep = {
        "episode_id": episode_id, "seed": res.seed, "scenario": json.dumps(res.scenario), "home": home_id,
        "away": away_id, "score_home": res.score[0], "score_away": res.score[1], "end_cause": res.end_cause,
        "duration_s": res.duration_s, "caps": json.dumps(res.caps), "kinds": json.dumps(res.kinds),
        "xt_moves": json.dumps(moves), "xt_shots": json.dumps(shots),
        "shots_home": sum(1 for e in res.events if e["type"] == "shot_taken" and e["team"] == 0),
        "shots_away": sum(1 for e in res.events if e["type"] == "shot_taken" and e["team"] == 1),
        "goals_home": sum(1 for e in res.events if e["type"] == "goal" and e["team"] == 0),
        "goals_away": sum(1 for e in res.events if e["type"] == "goal" and e["team"] == 1),
        "sim_config_hash": res.sim_config_hash,
    }
    return rows, ep


class ParquetLog:
    """Buffered writer: ``<root>/run=<run>/date=<YYYY-MM-DD>/{decisions,episodes}-NNNN.parquet``."""

    def __init__(self, root: str | Path, run_id: str, flush_every: int = 5000) -> None:
        self.dir = Path(root) / f"run={run_id}" / f"date={date.today().isoformat()}"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.tracking_dir = Path(root) / f"run={run_id}" / "tracking"
        self.flush_every = flush_every
        self.rows: list[dict] = []
        self.eps: list[dict] = []
        self.part = len(list(self.dir.glob("decisions-*.parquet")))
        self.n_rows = 0

    def add(self, rows: list[dict], ep: dict) -> None:
        self.rows.extend(rows)
        self.eps.append(ep)
        self.n_rows += len(rows)
        if len(self.rows) >= self.flush_every:
            self.flush()

    def save_tracking(self, episode_id: str, payload: dict) -> Path:
        self.tracking_dir.mkdir(parents=True, exist_ok=True)
        path = self.tracking_dir / f"{episode_id}.json.gz"
        with gzip.open(path, "wt") as fh:
            json.dump(payload, fh, separators=(",", ":"))
        return path

    def flush(self) -> None:
        if not self.rows and not self.eps:
            return
        if self.rows:
            pq.write_table(pa.Table.from_pylist(self.rows, DECISION_SCHEMA),
                           self.dir / f"decisions-{self.part:04d}.parquet")
        if self.eps:
            pq.write_table(pa.Table.from_pylist(self.eps, EPISODE_SCHEMA),
                           self.dir / f"episodes-{self.part:04d}.parquet")
        self.part += 1
        self.rows, self.eps = [], []


def load_table(root: str | Path, kind: str = "decisions", columns: list[str] | None = None) -> pa.Table:
    """Load every ``kind`` Parquet file under ``root`` (any run / date partition)."""
    files = sorted(Path(root).rglob(f"{kind}-*.parquet"))
    if not files:
        raise FileNotFoundError(f"no {kind} files under {root}")
    tables = []
    for f in files:
        names = pq.read_schema(f).names
        cols = [c for c in columns if c in names] if columns else None
        t = pq.read_table(f, columns=cols)
        for c in columns or []:
            if c not in t.column_names:
                # Older logs predate this column; surface it as nulls rather than failing.
                t = t.append_column(c, pa.nulls(t.num_rows))
        tables.append(t.select(columns) if columns else t)
    return pa.concat_tables(tables, promote_options="default")


def to_records(table: pa.Table) -> list[dict[str, Any]]:
    return table.to_pylist()


def json_col(table: pa.Table, name: str) -> list[Any]:
    return [json.loads(x) if x else None for x in table.column(name).to_pylist()]


def summary_array(values) -> dict[str, float]:
    a = np.asarray(values, dtype=float)
    if a.size == 0:
        return {"n": 0, "mean": 0.0}
    return {"n": int(a.size), "mean": float(a.mean()), "std": float(a.std())}
