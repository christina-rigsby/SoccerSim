"""Example clips of plays and the opponent's counter-plays, viewable straight from the repo.

For each chosen play, short games are run with the play forced for the home team (whenever
its own triggers hold) against a scripted style, until a clip is found in which the away
team is running a play of its own during ours. Each clip is saved as an animated GIF
(GitHub shows these inline), indexed in a ``README.md`` with the outcome, and collected
in one interactive replay page with the decision inspector.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..config import load_config
from ..schema import load_library
from ..schema.models import Play
from .replay import save_gif
from .replay_html import episode_payload, render_replay_html

DEFAULT_PLAYS = (
    # hand-written build-up plays (D-046)
    "cb_carry_into_midfield", "fullback_outlet_bounce", "long_ball_to_target", "pivot_drop_back_three",
    "switch_through_keeper", "winger_checks_short",
    # starter library plays
    "switch_of_play", "third_man_combination", "wide_overlap_cross", "through_ball_behind_high_line",
    "direct_counterattack", "one_two_wall_pass",
)


def _scenario_types(play: Play) -> tuple[tuple[str, ...], int]:
    from ..selfplay.league import BAND_SCENARIOS
    from ..sim.play_scenarios import PLAY_SCENARIOS

    if play.id in PLAY_SCENARIOS:
        return PLAY_SCENARIOS[play.id]
    band = ((play.provenance or {}).get("archive_cell") or {}).get("band", "mid_opp")
    return (BAND_SCENARIOS.get(band, "random_open_play"),), 0


def find_example(lib: dict[str, Play], play_id: str, style: str, max_seeds: int = 80,
                 min_duration_s: float = 1.5) -> dict[str, Any] | None:
    """The first clip where ``play_id`` runs and the opponent runs a play during it (else the
    first clip where it runs at all)."""
    from ..generator.train import forced_scenario
    from ..sim.env import MatchEnv
    from ..sim.play_scenarios import run_play

    types, attacking = _scenario_types(lib[play_id])
    env = MatchEnv()
    fallback = None
    for seed in range(max_seeds):
        sc = forced_scenario(types[seed % len(types)], attacking, seed)
        run = run_play(lib, play_id, seed, sc, max_time_s=25.0, env=env, opponent_style=style)
        rec = run.forced_record(play_id)
        if rec is None or rec["duration_s"] < min_duration_s:
            continue  # too short to show anything
        t0, t1 = rec["t_start"], rec["t_end"]
        counter = [p for p in run.result.plays if p["team"] == 1 and p["t_start"] < t1 and p["t_end"] > t0]
        ex = {"play_id": play_id, "style": style, "seed": seed, "scenario": sc, "result": run.result, "rec": rec,
              "counter": counter}
        if counter:
            return ex
        fallback = fallback or ex
    return fallback


def _clip(ex: dict[str, Any], before: float = 0.8, after: float = 1.5) -> dict[str, Any]:
    rec = ex["rec"]
    lo, hi = rec["t_start"] - before, rec["t_end"] + after
    sc = ex["scenario"]
    counter = ", ".join(sorted({p["play_id"] for p in ex["counter"]})) or "none (base shape)"
    title = (f"{ex['play_id']} v {ex['style']} ({counter}) · {sc.home_formation} v {sc.away_formation} · "
             f"{rec['end_reason'].replace('_', ' ')}")
    ep = episode_payload(ex["result"], title)
    ep["frames"] = [f for f in ep["frames"] if lo <= f["t"] <= hi]
    ep["plays"] = [p for p in ep["plays"] if p["t_start"] < hi and p["t_end"] > lo]
    ep["decisions"] = [d for d in ep["decisions"] if lo <= d["t"] <= hi]
    ep["events"] = [e for e in ep["events"] if lo <= e["t"] <= hi]
    return ep


def build_play_examples(out_dir: str | Path, play_ids: tuple[str, ...] | list[str] | None = None,
                        styles: list[str] | None = None, heading: str = "Plays and counter-plays") -> dict[str, Any]:
    """GIF + README per play, and one interactive page, under ``out_dir``."""
    out = Path(out_dir)
    (out / "gifs").mkdir(parents=True, exist_ok=True)
    lib = load_library()
    lcfg = load_config("league")
    styles = styles or [s for s in lcfg["scripted_styles"] if s not in lcfg["held_out_styles"]]
    play_ids = [p for p in (play_ids or DEFAULT_PLAYS) if p in lib]
    rows, episodes = [], []
    for i, pid in enumerate(play_ids):
        style = styles[i % len(styles)]
        ex = find_example(lib, pid, style)
        if ex is None:
            rows.append({"play": pid, "style": style, "found": False})
            continue
        ep = _clip(ex)
        episodes.append(ep)
        gif = out / "gifs" / f"{pid}.gif"
        save_gif(ep["frames"], gif, step=2, fps=8)
        rec = ex["rec"]
        epv = None if rec.get("epv_start") is None or rec.get("epv_end") is None else rec["epv_end"] - rec["epv_start"]
        rows.append({"play": pid, "style": style, "found": True, "gif": f"gifs/{pid}.gif",
                     "counter": sorted({p["play_id"] for p in ex["counter"]}), "end": rec["end_reason"],
                     "duration": rec["duration_s"], "epv": epv, "steps": rec["steps_visited"],
                     "formations": f"{ex['scenario'].home_formation} v {ex['scenario'].away_formation}",
                     "scenario": ex["scenario"].type, "seed": ex["seed"]})
    (out / "play_examples.html").write_text(render_replay_html(episodes, heading))
    (out / "README.md").write_text(_readme(rows, heading))
    return {"examples": sum(r["found"] for r in rows), "with_counter_play": sum(bool(r.get("counter")) for r in rows),
            "dir": str(out)}


def _readme(rows: list[dict[str, Any]], heading: str) -> str:
    lines = [
        f"# {heading}", "",
        "Short clips of a play (blue, home) and what the opponent (red, a scripted style) was running at the same",
        "time. Each clip starts just before the play is called and ends just after it finishes. Role labels show",
        "who the play bound; dashed lines are where each player is heading. Regenerate with",
        "`python scripts/selfplay.py examples`.", "",
        "`play_examples.html` has the same clips with the decision inspector (every candidate play and why it was",
        "or wasn't feasible); download it and open it in a browser.", "",
        "| Play | Opponent style | Opponent's play during it | Outcome | EPV change |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        if not r["found"]:
            lines.append(f"| `{r['play']}` | {r['style']} | (no clip found) | | |")
            continue
        counter = ", ".join(f"`{c}`" for c in r["counter"]) or "none (base shape)"
        epv = "" if r["epv"] is None else f"{r['epv']:+.4f}"
        lines.append(f"| [`{r['play']}`](#{r['play']}) | {r['style']} | {counter} | "
                     f"{r['end'].replace('_', ' ')} after {r['duration']:.1f} s | {epv} |")
    lines.append("")
    for r in rows:
        if not r["found"]:
            continue
        counter = ", ".join(f"`{c}`" for c in r["counter"]) or "no play (base shape)"
        lines += [f"## {r['play']}", "",
                  f"Against **{r['style']}**, running {counter}. {r['formations']}, {r['scenario'].replace('_', ' ')} "
                  f"start. Steps reached: {' → '.join(r['steps'])}; ended: {r['end'].replace('_', ' ')}.", "",
                  f"![{r['play']}]({r['gif']})", ""]
    return "\n".join(lines)


def build_success_gallery(run_dir: str | Path, out_dir: str | Path, top: int = 12,
                          max_clips: int = 60) -> dict[str, Any]:
    """GIFs, a README and an interactive page of the generated plays that succeeded in a run.

    Clips come from ``<run>/generated_successes/`` (saved during league training and the
    final evaluation). The README shows the best ``top`` (one per play, by reward) with the
    play's full definition; the page holds up to ``max_clips``.
    """
    import gzip
    import json

    import yaml

    src = Path(run_dir) / "generated_successes"
    out = Path(out_dir)
    index = [json.loads(line) for line in (src / "index.jsonl").read_text().splitlines()] \
        if (src / "index.jsonl").exists() else []
    index.sort(key=lambda r: -(r.get("reward") or 0.0))
    (out / "gifs").mkdir(parents=True, exist_ok=True)
    for old in (out / "gifs").glob("*.gif"):
        old.unlink()
    seen, best = set(), []
    for r in index:
        if r["play_id"] not in seen:
            seen.add(r["play_id"])
            best.append(r)
    best = best[:top]
    run = Path(run_dir).name
    lines = [f"# Generated plays that worked · {run.replace('_', ' ')}", "",
             f"{len(index)} times a generated play succeeded in this run ({len({r['play_id'] for r in index})} "
             "different plays), during league training or the final evaluation. A generated play counts as "
             "successful when it reached its own success condition or gained at least 0.005 EPV. Below, the best "
             "instance of each play (by reward), with what the opponent was running and the play's full definition.",
             "", "`generated_successes.html` has every clip with the decision inspector; download it and open it in a "
             "browser.", "",
             "| Play | By | Against | Opponent's play | Why it counts | Reward | Stage |",
             "|---|---|---|---|---|---|---|"]
    for r in best:
        counter = ", ".join(f"`{c}`" for c in r.get("counter_plays") or []) or "none (base shape)"
        lines.append(f"| [`{r['play_id']}`](#{r['play_id']}) | {r['player']} | {r['opponent']} | {counter} | "
                     f"{'; '.join(r['why'])} | {r['reward']:+.4f} | {r['stage']} (update {r['update']}) |")
    lines.append("")
    episodes = []
    for r in index[:max_clips]:
        clip = json.loads(gzip.decompress((src / r["file"]).read_bytes()))
        ep = clip["replay"]
        ep["title"] = (f"{r['play_id']} by {r['player']} v {r['opponent']} · reward {r['reward']:+.4f} · "
                       f"{r['end_reason'].replace('_', ' ')}")
        episodes.append(ep)
        if r in best:
            gif = out / "gifs" / f"{r['play_id']}.gif"
            save_gif(ep["frames"], gif, step=2, fps=8)
            counter = ", ".join(f"`{c}`" for c in r.get("counter_plays") or []) or "no play (base shape)"
            lines += [f"## {r['play_id']}", "",
                      f"Called by **{r['player']}** against **{r['opponent']}** (running {counter}); steps reached: "
                      f"{' → '.join(r.get('steps') or [])}; ended: {r['end_reason'].replace('_', ' ')}; reward "
                      f"{r['reward']:+.4f}.", "", f"![{r['play_id']}](gifs/{r['play_id']}.gif)", "",
                      "<details><summary>Play definition (YAML)</summary>", "", "```yaml",
                      yaml.safe_dump(clip["play_yaml"], sort_keys=False, width=110).rstrip(), "```", "", "</details>",
                      ""]
    (out / "README.md").write_text("\n".join(lines))
    (out / "generated_successes.html").write_text(render_replay_html(episodes, f"Generated plays that worked · {run}"))
    return {"successes": len(index), "plays": len(seen), "in_readme": len(best), "in_page": len(episodes),
            "dir": str(out)}
