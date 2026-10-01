"""Self-play training report: one HTML page that shows what Module 3 is doing.

Collects the artefacts the pipeline writes — Phase A logs, critic / generator metrics,
league state (history, Elo, payoff, PFSP), the QD archive, promotions, the fitted xT —
and renders them with the inline SVG charts in ``report_template.html``. Highlight
replays (games where the generator filled a library gap) are written next to it as
``selfplay_replays.html`` by :func:`build_highlights`.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np

from ..dashboard.xt import load_xt, placeholder_xt
from ..dashboard.zones import zone_of
from ..schema.vocab import BANDS, LANES

_TEMPLATE = Path(__file__).with_name("report_template.html")
POSSESSION = ("in_possession", "transition_attack", "set_piece")


def _read(path: Path) -> Any:
    return json.loads(path.read_text()) if path.exists() else None


def gap_analysis(root: str | Path, cache: Path | None = None, max_rows: int = 120000) -> dict[str, Any]:
    """Where and how often no non-fallback library play is feasible (in possession)."""
    if cache is not None and cache.exists():
        return json.loads(cache.read_text())
    from ..selfplay.logging import load_table

    t = load_table(root, "decisions", ["state", "side", "candidates", "library_gap", "phase", "chosen",
                                       "chosen_source", "reward"])
    rows = t.slice(0, min(max_rows, t.num_rows)).to_pylist()
    zone_n: Counter = Counter()
    zone_gap: Counter = Counter()
    feas: dict[str, Counter] = defaultdict(Counter)
    reasons: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        if r["phase"] not in POSSESSION or not r["state"]:
            continue
        st = json.loads(r["state"])
        if not st:
            continue
        z = zone_of(np.asarray(st["ball"], dtype=float), float(r["side"] or 1.0))
        zone_n[z] += 1
        zone_gap[z] += bool(r["library_gap"])
        for c in json.loads(r["candidates"]):
            if c["source"] != "library":
                continue
            feas[c["play_id"]]["n"] += 1
            feas[c["play_id"]]["ok"] += c["feasible"]
            reasons[c["play_id"]][c["reason"] or "feasible"] += 1
    zones = {z: {"n": zone_n[z], "gap_rate": zone_gap[z] / zone_n[z]} for z in zone_n}
    plays = {p: {"n": c["n"], "feasible_rate": c["ok"] / max(c["n"], 1),
                 "top_reasons": dict(reasons[p].most_common(4))} for p, c in feas.items()}
    out = {"rows": len(rows), "zones": zones, "plays": plays,
           "overall_gap_rate": sum(zone_gap.values()) / max(sum(zone_n.values()), 1)}
    if cache is not None:
        cache.write_text(json.dumps(out))
    return out


def collect(models_dir: str | Path, root: str | Path) -> dict[str, Any]:
    models = Path(models_dir)
    league = models / "league"
    data: dict[str, Any] = {}
    from ..eval.reports import summarize

    try:
        data["phase_a"] = summarize(root)
    except FileNotFoundError:
        data["phase_a"] = None
    try:
        data["gaps"] = gap_analysis(root, models / "gap_analysis.json")
    except FileNotFoundError:
        data["gaps"] = None
    data["critic"] = _read(models / "critic_metrics.json")
    data["generator"] = _read(models / "generator_metrics.json")
    st = _read(league / "state.json") or {}
    data["league"] = {k: st.get(k) for k in ("update", "history", "elo", "payoff", "flags", "final_eval",
                                             "snapshots")}
    arch = _read(league / "archive.json")
    if arch:
        from ..selfplay.qd_archive import Archive

        a = Archive(arch["min_evals"])
        a.plays = arch["plays"]
        cells = a.cells()
        grid: dict[str, dict] = {}
        for c in cells.values():
            band, lane = c["desc"][0], c["desc"][1]
            g = grid.setdefault(f"{band}.{lane}", {"plays": 0, "elites": 0, "best": None})
            g["plays"] += c["plays"]
            g["elites"] += bool(c["elite"])
            m = c["elite_mean"] if c["elite"] else None
            if m is not None and (g["best"] is None or m > g["best"]):
                g["best"] = m
        top = sorted(((c["elite_mean"], c) for c in cells.values() if c["elite"]), key=lambda x: -x[0])[:10]
        data["archive"] = {"coverage": a.coverage(), "grid": grid, "min_evals": a.min_evals,
                           "top": [{"id": c["elite"], "desc": c["desc"], "mean": m, "n": c.get("elite_n")}
                                   for m, c in top]}
    else:
        data["archive"] = None
    promo = _read(league / "promotion.json")
    data["promotion"] = promo
    from ..selfplay.promote import PROMOTED_DIR, run_numbers

    run = (promo or {}).get("run") or st.get("promotion_run") or (run_numbers() or [None])[-1]
    promoted = []
    if run is not None:
        for p in sorted((PROMOTED_DIR / f"run_{run}").glob("*.yaml")):
            promoted.append({"id": p.stem, "yaml": p.read_text()})
    data["promoted"] = promoted
    data["promotion_run"] = run
    ph = placeholder_xt().values
    fit = load_xt({**json.loads(json.dumps(_xt_cfg())), "source": "fitted"}).values
    data["xt"] = {"placeholder": np.round(ph, 4).tolist(), "fitted": np.round(fit, 4).tolist()}
    data["bands"] = list(BANDS)
    data["lanes"] = list(LANES)
    data["meta"] = _read(models / "meta.json")
    data["replays"] = (models.parent.parent / "out" / "selfplay_replays.html").exists()
    return data


def _xt_cfg() -> dict:
    from ..config import load_config

    return load_config("xt_placeholder")


def render(data: dict[str, Any], fragment: bool = False) -> str:
    tpl = _TEMPLATE.read_text()
    blob = json.dumps(data, separators=(",", ":"), default=float).replace("</", "<\\/")
    body = tpl.replace("__DATA__", blob)
    if fragment:
        return body
    return ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
            f"</head>\n<body>\n{body}\n</body>\n</html>\n")


def build_report(models_dir: str | Path, root: str | Path, out: str | Path, fragment: bool = False) -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(collect(models_dir, root), fragment))
    return out


def build_highlights(models_dir: str | Path, out: str | Path, n_games: int = 12, keep: int = 4,
                     workers: int = 4, fragment: bool = False, seed: int = 7) -> dict[str, Any]:
    """Play the trained agent (generator on the library-gap trigger) against scripted styles
    and keep the games where generated plays were actually called, plus one library-only
    baseline game, as an interactive replay page."""
    from ..config import load_config
    from ..selfplay.runner import run_jobs
    from ..sim.scenarios import Scenario

    league_dir = Path(models_dir) / "league"
    ckpt = league_dir if (league_dir / "main.pt").exists() else Path(models_dir)
    gfile = "main.pt" if ckpt == league_dir else "generator.pt"
    styles = list(load_config("league")["scripted_styles"])
    rng = np.random.default_rng(seed)
    types = ("final_third_attack", "transition_win", "mid_progression", "random_open_play")
    jobs = []
    for k in range(n_games):
        sc = Scenario(type=types[k % len(types)], attacking_team=0, minute=float(rng.uniform(10, 85)))
        jobs.append({
            "episode_id": f"H{k:02d}", "seed": int(rng.integers(1 << 31)), "scenario": sc.to_dict(),
            "home": {"id": "agent", "kind": "agent", "checkpoint": str(ckpt), "generator_file": gfile,
                     "activation": "on_gap", "k": 4, "critic": True, "gen_temperature": 0.8},
            "away": {"id": styles[k % len(styles)], "kind": "style", "style": styles[k % len(styles)]},
            "randomise": False, "save_tracking": True, "max_time_s": 30.0,
            "title": f"Agent vs {styles[k % len(styles)]} · {sc.type}",
        })
    base = dict(jobs[0], episode_id="H-lib", home={"id": "library", "kind": "library"},
                title=f"Library only vs {styles[0]} · {jobs[0]['scenario']['type']} (baseline)")
    results: list[dict] = []
    run_jobs([*jobs, base], None, workers=workers, on_result=results.append, progress_every=0)
    agent = [r for r in results if r["episode"]["episode_id"] != "H-lib"]

    def interest(r: dict) -> float:
        gen = sum(p["source"] != "library" for p in r["plays"] if p["team"] == 0)
        shots = r["episode"]["shots_home"] + 2 * r["episode"]["goals_home"]
        return gen + 2 * shots

    agent.sort(key=interest, reverse=True)
    chosen = [r for r in agent if interest(r) > 0][:keep] or agent[:1]
    chosen += [r for r in results if r["episode"]["episode_id"] == "H-lib"]
    payload = [r["tracking"] for r in chosen]
    for p, r in zip(payload, chosen, strict=True):
        p["title"] = next(j["title"] for j in [*jobs, base] if j["episode_id"] == r["episode"]["episode_id"])
    from .replay_html import render_replay_html

    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_replay_html(payload, "Self-play highlights", fragment))
    return {"games": len(results), "kept": len(payload),
            "generated_calls": sum(sum(p["source"] != "library" for p in r["plays"] if p["team"] == 0)
                                   for r in agent),
            "shots_agent": sum(r["episode"]["shots_home"] for r in agent),
            "goals_agent": sum(r["episode"]["goals_home"] for r in agent)}
