"""Reliable team evaluation: many paired games, reported with their uncertainty.

The league's validation round-robin played 8 short games per pair and scored them win/draw/loss,
mostly decided by a reward tie-break because goals are rare; its scores were only good to about
±0.06. This module measures teams so that a real improvement can be told from luck:

- **Continuous games.** Each game runs ``max_time_s`` (default 120 s) without stopping at a
  turnover or a goal (play restarts with a kick-off), so defending and winning the ball back
  count as much as attacking.
- **Measures, per game, from the team's side:** goal difference, xG difference (summed shot
  quality for minus against: much less noisy than goals and still rewards making and denying
  chances) and shot difference. The headline is the **xG difference per game**.
- **Paired design.** Every team plays the *same* scenarios (situation, formations, player
  capabilities, random seed) against every opponent, once from each side. Comparing two teams
  game by game on identical scenarios cancels most scenario luck: the paired difference has a
  much smaller standard error than comparing two separate averages.
- **Uncertainty.** Every mean comes with its standard error (SE); a difference larger than
  about 2 SE is unlikely to be luck.

Teams: ``library`` (hand-written ranking), every scripted style by name, ``lookahead`` (tries
each candidate play in copies of the game; ``lookahead_<rollouts>x<top_k>_<horizon>s`` sets its
parameters), and the learned teams ``library_critic`` (library plus the critic of the latest league run), ``selector``
(the library-only learned selector) and ``main`` (the latest run's critic + generator).
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

from ..config import load_config
from ..sim.scenarios import SCENARIO_TYPES, sample_scenario
from .policies import style_spec

LEARNED = ("library_critic", "selector", "main")


def latest_run_dir(models_dir: str | Path) -> Path | None:
    runs = sorted((d for d in (Path(models_dir) / "runs").glob("run_*") if (d / "state.json").exists()),
                  key=lambda d: int(d.name[4:]))
    return runs[-1] if runs else None


def team_spec(name: str, models_dir: str | Path = "data/models") -> dict[str, Any]:
    """Policy spec of a team, as it plays in evaluation (no exploration).

    A ``_noinst`` suffix gives the same team without player instincts (e.g. ``library_noinst``).
    """
    if name.endswith("_noinst"):
        return {**team_spec(name[: -len("_noinst")], models_dir), "id": name, "instincts": False}
    lcfg = load_config("league")
    if name in lcfg["scripted_styles"]:
        return style_spec(name, lcfg)
    if name == "library":
        return {"id": "library", "kind": "library", "temperature": 0.01}
    if name == "lookahead" or name.startswith("lookahead_"):
        # lookahead, or lookahead_<rollouts>x<top_k>_<horizon>s, e.g. lookahead_8x6_6s
        spec = {"id": name, "kind": "lookahead", "temperature": 0.01}
        if name != "lookahead":
            r, rest = name[len("lookahead_"):].split("x")
            k, h = rest.split("_")
            spec.update(rollouts=int(r), top_k=int(k), horizon_s=float(h.rstrip("s")))
        return spec
    if name == "selector":
        from .selector import selector_spec

        return selector_spec(models_dir)
    if name in ("library_critic", "main"):
        run = latest_run_dir(models_dir)
        if run is None:
            raise ValueError(f"team {name!r} needs a league run in {models_dir}/runs")
        spec = {"id": name, "kind": "agent", "checkpoint": str(run), "generator_file": "main.pt", "k": 4,
                "critic": True, "temperature": 0.01, "learner": None}
        if name == "main":
            return {**spec, "activation": "on_gap", "gen_temperature": 0.7}
        return {**spec, "generator": False}
    raise ValueError(f"unknown team {name!r}")


def scenarios(n: int, seed: int = 2024) -> list[dict[str, Any]]:
    """``n`` fixed evaluation scenarios, each with its own game seed (shared by every pairing)."""
    lcfg = load_config("league")
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(n):
        sc = sample_scenario(rng, SCENARIO_TYPES[:-2] + ("random_open_play",), tuple(lcfg["formations"]))
        out.append({"scenario": sc.to_dict(), "seed": int(rng.integers(1 << 31))})
    return out


def build_jobs(teams: list[str], opponents: list[str], n: int, seed: int = 2024, max_time_s: float = 120.0,
               models_dir: str | Path = "data/models") -> list[dict[str, Any]]:
    """Every team against every opponent on the same ``n`` scenarios, once from each side."""
    jobs = []
    specs = {t: team_spec(t, models_dir) for t in {*teams, *opponents}}
    for k, sc in enumerate(scenarios(n, seed)):
        for t in teams:
            for o in opponents:
                if o == t:
                    continue
                for side in (0, 1):
                    home, away = (t, o) if side == 0 else (o, t)
                    jobs.append({"episode_id": f"E-{t}-{o}-{k:04d}-{side}", "seed": sc["seed"],
                                 "scenario": sc["scenario"], "home": {**specs[home], "id": home},
                                 "away": {**specs[away], "id": away}, "randomise": True,
                                 "max_time_s": max_time_s, "stop_on_goal": False, "stop_on_turnover": False,
                                 "eval": {"team": t, "opp": o, "k": k, "side": side}})
    return jobs


def game_record(res: dict[str, Any], team_side: int) -> dict[str, float]:
    """Per-game measures from one team's side (``team_side``: 0 home, 1 away)."""
    me, them = team_side, 1 - team_side
    gf = ga = 0
    xgf = xga = 0.0
    sf = sa = 0
    for e in res.get("events", []):
        if e["type"] == "goal":
            gf += e.get("team") == me
            ga += e.get("team") == them
        elif e["type"] == "shot_taken":
            xg = float((e.get("data") or {}).get("xg") or 0.0)
            if e.get("team") == me:
                xgf, sf = xgf + xg, sf + 1
            else:
                xga, sa = xga + xg, sa + 1
    return {"gd": gf - ga, "xgd": xgf - xga, "sd": sf - sa, "gf": gf, "ga": ga, "xgf": xgf, "xga": xga}


def run_evaluation(teams: list[str], opponents: list[str], n: int, workers: int = 4, seed: int = 2024,
                   max_time_s: float = 120.0, models_dir: str | Path = "data/models",
                   progress_every: int = 500) -> dict[str, Any]:
    from .runner import run_jobs

    jobs = build_jobs(teams, opponents, n, seed, max_time_s, models_dir)
    tags = {j["episode_id"]: j["eval"] for j in jobs}
    games: list[dict[str, Any]] = []

    def on_result(res: dict) -> None:
        tag = tags[res["episode"]["episode_id"]]
        side = tag["side"]  # the evaluated team is home when side == 0
        games.append({**tag, **game_record(res, side)})

    run_jobs(jobs, None, workers=workers, on_result=on_result, progress_every=progress_every)
    return {"teams": teams, "opponents": opponents, "scenarios": n, "seed": seed, "max_time_s": max_time_s,
            "games": games}


def _mse(x: list[float]) -> tuple[float, float]:
    a = np.asarray(x, float)
    return (float(a.mean()), float(a.std(ddof=1) / np.sqrt(len(a)))) if len(a) > 1 else (float(a.mean()), float("nan"))


def summarise(ev: dict[str, Any], baseline: str | None = None) -> dict[str, Any]:
    """Per team: mean ± SE of each measure overall and per opponent; paired difference vs ``baseline``."""
    by_team: dict[str, list[dict]] = defaultdict(list)
    for g in ev["games"]:
        by_team[g["team"]].append(g)
    out: dict[str, Any] = {"teams": {}, "paired_vs": baseline, "paired": {}}
    for t, gs in by_team.items():
        row = {m: _mse([g[m] for g in gs]) for m in ("xgd", "gd", "sd")}
        row["games"] = len(gs)
        row["per_opponent"] = {o: {m: _mse([g[m] for g in gs if g["opp"] == o]) for m in ("xgd", "gd")}
                               for o in sorted({g["opp"] for g in gs})}
        out["teams"][t] = row
    if baseline and baseline in by_team:
        base = {(g["opp"], g["k"], g["side"]): g for g in by_team[baseline]}
        for t, gs in by_team.items():
            if t == baseline:
                continue
            pairs = [(g, base[(g["opp"], g["k"], g["side"])]) for g in gs if (g["opp"], g["k"], g["side"]) in base]
            if pairs:
                out["paired"][t] = {m: _mse([a[m] - b[m] for a, b in pairs]) for m in ("xgd", "gd")}
                out["paired"][t]["games"] = len(pairs)
    return out


def markdown(ev: dict[str, Any], summ: dict[str, Any]) -> str:
    def f(ms: tuple[float, float], d: int = 3) -> str:
        return f"{ms[0]:+.{d}f} ± {ms[1]:.{d}f}"

    lines = ["# Team evaluation\n",
             f"{ev['scenarios']} scenarios x {len(ev['opponents'])} opponents x 2 sides, continuous "
             f"{ev['max_time_s']:.0f}-second games. Per game, from the team's side; ± is one standard error "
             "(a difference beyond about 2 SE is unlikely to be luck).\n",
             "| Team | xG difference | Goal difference | Shot difference | Games |", "|---|---|---|---|---|"]
    for t, r in sorted(summ["teams"].items(), key=lambda kv: -kv[1]["xgd"][0]):
        lines.append(f"| {t} | {f(r['xgd'])} | {f(r['gd'])} | {f(r['sd'], 2)} | {r['games']} |")
    if summ["paired"]:
        lines += ["", f"## Paired against `{summ['paired_vs']}` (same scenarios, same opponents)\n",
                  "| Team | xG difference minus baseline's | Goal difference minus baseline's | Pairs |",
                  "|---|---|---|---|"]
        for t, r in sorted(summ["paired"].items(), key=lambda kv: -kv[1]["xgd"][0]):
            lines.append(f"| {t} | {f(r['xgd'])} | {f(r['gd'])} | {r['games']} |")
    lines += ["", "## xG difference per opponent\n"]
    opps = sorted({o for r in summ["teams"].values() for o in r["per_opponent"]})
    lines += ["| Team | " + " | ".join(opps) + " |", "|---|" + "---|" * len(opps)]
    for t, r in summ["teams"].items():
        lines.append(f"| {t} | " + " | ".join(f(r["per_opponent"][o]["xgd"], 2) if o in r["per_opponent"] else "–"
                                               for o in opps) + " |")
    return "\n".join(lines) + "\n"


def save(ev: dict[str, Any], summ: dict[str, Any], out_dir: str | Path) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "games.json").write_text(json.dumps(ev))
    (out / "summary.json").write_text(json.dumps(summ, indent=1))
    (out / "README.md").write_text(markdown(ev, summ))
    return out
