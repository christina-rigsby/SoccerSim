"""League training for the generator (spec §11 Phase C; M9).

Players:

- **main** — the learning agent; plays both sides with shared weights.
- **snapshots** — frozen copies of main every ``snapshot_every`` updates.
- **main exploiter** — trained only against the current main agent; reset to the Phase B
  generator every ``main_exploiter_reset_every`` updates.
- **league exploiter** — trained against the whole pool.
- **scripted styles** — library-only teams with fixed play preferences and their own selection
  temperature; the ``held_out_styles`` are kept out of training entirely and only used for
  evaluation (they are not in Phase A data either).

Opponents are sampled with prioritised fictitious self-play. Each update runs games in a
process pool, logs them to Parquet (continual critic data), updates every learner with
PPO, updates Elo and the payoff matrix, feeds executed generated plays into the
MAP-Elites archive, and spends some evaluations refining archive contenders.
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any

import numpy as np
import torch

from ..config import load_config
from ..eval.elo import Elo, Payoff
from ..generator.agent import load_critic, load_generator, save_model
from ..generator.data import play_ids
from ..generator.ppo import critic_baseline, ppo_update
from ..schema import load_library
from ..sim.env import held_out_sim
from ..sim.scenarios import SCENARIO_TYPES, sample_scenario
from .pfsp import pfsp_weights
from .policies import check_styles, style_spec
from .qd_archive import Archive, descriptor, seed_archive
from .runner import run_jobs
from .runs import (
    LEARNERS,
    PROMOTED_DIR,
    check_base_models,
    latest_run_dir,
    next_run_number,
    plan_start,
    pool_definition,
    pool_fingerprint,
    pool_label,
    prior_promoted,
    read_state,
    run_dirs,
    runs_root,
)

BAND_SCENARIOS = {"own_third": "mid_progression", "mid_own": "mid_progression", "mid_opp": "random_open_play",
                  "final_third": "final_third_attack"}


class League:
    """One league run. ``run_dir=None`` creates the next run (``data/models/runs/run_<N>/``);
    passing an existing run directory resumes it."""

    RUN_KEYS = ("run", "promotion_run", "pool", "pool_fingerprint", "continued_from", "start_from", "start_reason",
                "seeded_from_runs", "seeds_to_evaluate", "gate")

    def __init__(self, models_dir: str | Path, data_root: str | Path, profile: str | None = None,
                 seed: int = 0, run_dir: str | Path | None = None, start_mode: str = "auto",
                 promoted_root: str | Path | None = None) -> None:
        self.models = Path(models_dir)
        self.root = Path(data_root)
        self.tcfg = load_config("training")
        self.prof = profile or self.tcfg["profile"]
        self.lcfg = load_config("league")
        self.rng = np.random.default_rng(seed)
        self.lib = load_library()
        check_styles(self.lcfg, self.lib)
        self.promoted_root = Path(promoted_root) if promoted_root else PROMOTED_DIR
        min_evals = self.tcfg["qd"][f"min_evals_{self.prof}"]
        if run_dir is None:
            n = next_run_number(self.models, self.promoted_root)
            self.dir = runs_root(self.models) / f"run_{n}"
            self._create(n, start_mode, min_evals)
        else:
            self.dir = Path(run_dir)
        self.state_path = self.dir / "state.json"
        st = json.loads(self.state_path.read_text()) if self.state_path.exists() else {}
        self.run_info = {k: st.get(k) for k in self.RUN_KEYS}
        self.update = st.get("update", 0)
        self.snapshots: list[str] = st.get("snapshots", [])
        self.elo = Elo(self.lcfg["elo_k"], self.lcfg["initial_elo"])
        self.elo.ratings = st.get("elo", {})
        self.payoff = Payoff.from_json(st.get("payoff", {}))
        self.history: list[dict] = st.get("history", [])
        self.flags: list[str] = st.get("flags", [])
        self.final_eval: dict = st.get("final_eval", {})
        self.archive = Archive.load(self.dir / "archive.json", min_evals)
        self.styles = [s for s in self.lcfg["scripted_styles"] if s not in self.lcfg["held_out_styles"]]
        self.gens = {n: load_generator(self.dir / f"{n}.pt") for n in LEARNERS}
        self.ref = load_generator(self.dir / "ref.pt")
        self.critic = load_critic(self.dir / "critic.pt") if (self.dir / "critic.pt").exists() else None
        lr = self.tcfg["ppo"][self.prof]["lr"]
        self.opts = {n: torch.optim.Adam(self.gens[n].parameters(), lr=lr) for n in LEARNERS}
        self.gen_ident = play_ids(self.lib).index("generated")

    @property
    def run(self) -> int | None:
        return self.run_info.get("run")

    def _create(self, n: int, start_mode: str, min_evals: int) -> None:
        """Set up run ``n``: starting generator (option 4 guardrails), KL anchor, seeded archive."""
        check_base_models(self.models, self.lcfg)
        plan = plan_start(self.models, self.lcfg, start_mode)
        prev_dir = latest_run_dir(self.models)
        self.dir.mkdir(parents=True, exist_ok=False)
        for f in ("critic.pt", "response.pt"):
            if (self.models / f).exists():
                shutil.copy(self.models / f, self.dir / f)
        # The KL anchor and the exploiters' reset point are this run's pretrained generator.
        phase_b = self.models / "generator.pt"
        for name in ("ref.pt", "main_exploiter.pt", "league_exploiter.pt"):
            shutil.copy(phase_b, self.dir / name)
        shutil.copy(plan["start_from"], self.dir / "main.pt")
        shutil.copy(plan["start_from"], self.dir / "start.pt")
        state: dict[str, Any] = {
            "run": n, "promotion_run": n, "pool": pool_definition(self.lcfg),
            "pool_fingerprint": pool_fingerprint(self.lcfg), "continued_from": plan["continued_from"],
            "start_from": plan["start_from"], "start_reason": plan["reason"], "update": 0,
        }
        if plan["continued_from"] is not None and prev_dir is not None:
            # Carry the opponent statistics so PFSP keeps focusing on what the last run struggled
            # with, and keep the previous run's final generator in the pool so it is not forgotten.
            prev = read_state(prev_dir)
            state["payoff"] = prev.get("payoff", {})
            state["elo"] = dict(prev.get("elo", {}))
            snap = f"run{prev.get('run')}@final"
            shutil.copy(prev_dir / "main.pt", self.dir / f"{snap.replace('@', '_')}.pt")
            state["snapshots"] = [snap]
            state["elo"][snap] = state["elo"].get("main", self.lcfg["initial_elo"])
        # Promoted plays adopted into the library compete as library plays, not archive seeds.
        prior = [p for p in prior_promoted(before_run=n, root=self.promoted_root) if p.id not in self.lib]
        archive = Archive(min_evals)
        # Earlier evaluations only count if they were earned against this same opponent pool.
        fp = pool_fingerprint(self.lcfg)
        same_pool = {k for k, d in run_dirs(self.models).items() if read_state(d).get("pool_fingerprint") == fp}
        state["seeds_to_evaluate"] = seed_archive(archive, prior, keep_evals_from=same_pool)
        archive.save(self.dir / "archive.json")
        state["seeded_from_runs"] = sorted({p.provenance.get("run") for p in prior if p.provenance})
        (self.dir / "state.json").write_text(json.dumps(state, indent=1, default=str))

    # -- specs -------------------------------------------------------------------------------

    def spec(self, pid: str) -> dict[str, Any]:
        if pid in self.lcfg["scripted_styles"]:
            return style_spec(pid, self.lcfg)
        if pid == "library":
            return {"id": "library", "kind": "library", "temperature": 0.01}
        file = f"{pid}.pt" if pid in LEARNERS else f"{pid.replace('@', '_')}.pt"
        return {"id": pid, "kind": "agent", "checkpoint": str(self.dir), "generator_file": file,
                "activation": "always", "k": 4, "critic": True, "temperature": 0.01,
                "gen_temperature": self.lcfg.get("train_gen_temperature", 1.2),
                "learner": pid if pid in LEARNERS else None}

    def pool(self) -> list[str]:
        return ["main", *self.snapshots, "main_exploiter", "league_exploiter", *self.styles]

    def _job(self, a: str, b: str, k: int, tag: str) -> dict[str, Any]:
        sc = sample_scenario(self.rng, SCENARIO_TYPES[:-2] + ("random_open_play",), tuple(self.lcfg["formations"]))
        home, away = (a, b) if self.rng.random() < 0.5 else (b, a)
        return {"episode_id": f"L{self.update:03d}-{tag}-{k:03d}", "seed": int(self.rng.integers(1 << 31)),
                "scenario": sc.to_dict(), "home": self.spec(home), "away": self.spec(away), "randomise": True,
                "save_generated_successes": True}

    def save_success_clips(self, res: dict, stage: str) -> int:
        """Keep the clips of generated plays that succeeded (``<run>/generated_successes/``)."""
        import gzip

        clips = res.get("success_clips") or []
        if not clips:
            return 0
        d = self.dir / "generated_successes"
        d.mkdir(exist_ok=True)
        with open(d / "index.jsonl", "a") as idx:
            for c in clips:
                name = f"{c['episode_id']}-{c['play_id']}-{int(c['t_start'] * 10):04d}.json.gz"
                (d / name).write_bytes(gzip.compress(json.dumps(c, default=str).encode()))
                meta = {k: v for k, v in c.items() if k not in ("replay", "play_yaml")}
                idx.write(json.dumps({**meta, "file": name, "stage": stage, "update": self.update}, default=str) + "\n")
        return len(clips)

    # -- one update ---------------------------------------------------------------------------

    def run_update(self, workers: int = 4) -> dict[str, Any]:
        t0 = time.time()
        pc = self.tcfg["ppo"][self.prof]
        n = pc["episodes_per_update"]
        pool = self.pool()
        jobs = []
        opp_main = [o for o in pool]
        w = pfsp_weights("main", opp_main, self.payoff, self.lcfg["pfsp_weighting"])
        for k in range(n):
            jobs.append(self._job("main", opp_main[int(self.rng.choice(len(opp_main), p=w))], k, "main"))
        for k in range(max(1, n // 2)):
            jobs.append(self._job("main_exploiter", "main", k, "mx"))
        lx_pool = [o for o in pool if o != "league_exploiter"]
        wl = pfsp_weights("league_exploiter", lx_pool, self.payoff, self.lcfg["pfsp_weighting"])
        for k in range(max(1, n // 2)):
            jobs.append(self._job("league_exploiter", lx_pool[int(self.rng.choice(len(lx_pool), p=wl))], k, "lx"))

        rollouts: dict[str, list] = {x: [] for x in LEARNERS}
        games = []
        gen_stats = {"sampled": 0, "valid": 0}
        main_choices = {"generated": 0, "total": 0}

        def on_result(res: dict) -> None:
            self.save_success_clips(res, "league")
            ep = res["episode"]
            ids = (ep["home"], ep["away"])
            for team in (0, 1):
                learner = ids[team] if ids[team] in LEARNERS else None
                rl = res.get("rollouts", {}).get(team, [])
                if learner:
                    rollouts[learner].extend(rl)
                gs = res.get("gen_stats", {}).get(team)
                if gs and ids[team] == "main":
                    gen_stats["sampled"] += gs["sampled"]
                    gen_stats["valid"] += gs["valid"]
            rew = [sum(r["reward"] for r in res["rows"] if r["team"] == t) for t in (0, 1)]
            gd = ep["goals_home"] - ep["goals_away"]
            score = 1.0 if gd > 0 else 0.0 if gd < 0 else (0.5 if abs(rew[0] - rew[1]) < 0.005 else
                                                             float(rew[0] > rew[1]))
            games.append((ids[0], ids[1], score, rew[0] - rew[1]))
            for r in res["rows"]:
                if ids[r["team"]] == "main":
                    main_choices["total"] += 1
                    main_choices["generated"] += r["chosen_source"] != "library"
            for p in res["plays"]:
                if p["source"] != "library" and p.get("play_yaml"):
                    opp = ids[1 - p["team"]]
                    self.archive.add(p["play_yaml"], descriptor(p["play_yaml"], p.get("state"), p.get("side")),
                                     p.get("reward") or 0.0, opp)

        run_info = run_jobs(jobs, self.root, f"league_u{self.update:03d}", workers=workers, on_result=on_result,
                            progress_every=0)
        for a, b, s, dr in games:
            self.elo.update(a, b, s)
            self.payoff.add(a, b, s, dr)

        # PPO on every learner.
        ppo_stats = {}
        for name in LEARNERS:
            rl = rollouts[name]
            base = critic_baseline(self.critic, rl, self.gen_ident)
            ppo_stats[name] = ppo_update(self.gens[name], self.ref, rl, base, pc, self.opts[name])
            save_model(self.gens[name], self.dir / f"{name}.pt")
        self.update += 1
        if self.update % self.lcfg["snapshot_every"] == 0:
            snap = f"main@{self.update}"
            shutil.copy(self.dir / "main.pt", self.dir / f"{snap.replace('@', '_')}.pt")
            self.snapshots.append(snap)
            self.elo.ratings[snap] = self.elo.get("main")
        if self.update % self.lcfg["main_exploiter_reset_every"] == 0:
            shutil.copy(self.dir / "ref.pt", self.dir / "main_exploiter.pt")
            self.gens["main_exploiter"] = load_generator(self.dir / "main_exploiter.pt")
            self.opts["main_exploiter"] = torch.optim.Adam(self.gens["main_exploiter"].parameters(), lr=pc["lr"])

        refine = self.refine_archive(workers)
        rec = {
            "update": self.update, "episodes": len(jobs), "decisions": run_info["decisions"],
            "wall_s": round(time.time() - t0, 1), "ppo": ppo_stats,
            "main_generated_share": main_choices["generated"] / max(main_choices["total"], 1),
            "validity": gen_stats["valid"] / max(gen_stats["sampled"], 1), "sampled": gen_stats["sampled"],
            "elo": {k: round(v, 1) for k, v in self.elo.ratings.items()},
            "pfsp": {o: round(float(x), 3) for o, x in zip(opp_main, w, strict=True)},
            "archive": self.archive.coverage(), "refined": refine,
        }
        self.history.append(rec)
        self.save()
        return rec

    # -- archive refinement and evaluation --------------------------------------------------------

    def refine_archive(self, workers: int, k: int = 6) -> int:
        """Forced evaluations of the most promising under-evaluated archive plays."""
        from ..generator.train import _eval_generated_job

        todo = self.archive.under_evaluated(k)
        if not todo:
            return 0
        rollouts = max(2, min(6, self.archive.min_evals))
        jobs = []
        for pid in todo:
            e = self.archive.plays[pid]
            for style in self.styles:
                jobs.append({"play": e["play"], "band": e["desc"][0], "opponent": style,
                             "seeds": [int(s) for s in self.rng.integers(0, 1 << 30, rollouts * 3)],
                             "rollouts": rollouts})
        import multiprocessing as mp

        with mp.get_context("fork").Pool(workers) as pool:
            results = pool.map(_eval_generated_job, jobs)
        for job, r in zip(jobs, results, strict=True):
            e = self.archive.plays[r["id"]]
            for rw in r["rewards"]:
                self.archive.add(e["play"], e["desc"], rw, job["opponent"], source="refine")
        return len(jobs)

    def evaluate_seeds(self, workers: int = 4) -> int:
        """Evaluate archive seeds carried in from a different opponent pool against this run's
        training styles, so they defend their niche on today's terms (D-045)."""
        from ..generator.train import _eval_generated_job

        todo = [pid for pid in (self.run_info.get("seeds_to_evaluate") or []) if pid in self.archive.plays]
        if not todo:
            return 0
        rollouts = max(2, -(-self.archive.min_evals // len(self.styles)))
        jobs = []
        for pid in todo:
            e = self.archive.plays[pid]
            for style in self.styles:
                jobs.append({"play": e["play"], "band": e["desc"][0], "opponent": style,
                             "seeds": [int(s) for s in self.rng.integers(0, 1 << 30, rollouts * 3)],
                             "rollouts": rollouts})
        import multiprocessing as mp

        with mp.get_context("fork").Pool(workers) as pool:
            results = pool.map(_eval_generated_job, jobs)
        for job, r in zip(jobs, results, strict=True):
            e = self.archive.plays[r["id"]]
            for rw in r["rewards"]:
                e["evals"].append([float(rw), job["opponent"], f"seed-reeval-run{e.get('prior_run')}"])
        self.run_info["seeds_to_evaluate"] = []
        self.save()
        return len(todo)

    def evaluate(self, n: int = 8, workers: int = 4, activation: str = "on_gap") -> dict[str, Any]:
        """Main agent vs every scripted style (held-out one included) vs the library baseline."""
        out: dict[str, Any] = {}
        styles = list(self.lcfg["scripted_styles"])
        for who in ("main", "library"):
            for style in styles:
                spec = self.spec(who)
                if spec["kind"] == "agent":
                    spec = {**spec, "activation": activation, "gen_temperature": 0.7}
                jobs = []
                # Matched games: the same seeds for main and library, different seeds per style.
                rng = np.random.default_rng(1234 + styles.index(style))
                for k in range(n):
                    sc = sample_scenario(rng, SCENARIO_TYPES[:-2] + ("random_open_play",))
                    jobs.append({"episode_id": f"E-{who}-{style}-{k}", "seed": int(rng.integers(1 << 31)),
                                 "scenario": sc.to_dict(), "home": spec, "away": self.spec(style), "randomise": True,
                                 "save_generated_successes": who == "main"})
                res = []
                run_jobs(jobs, None, workers=workers, on_result=res.append, progress_every=0)
                for x in res:
                    self.save_success_clips(x, "evaluation")
                rew = [r["reward"] for x in res for r in x["rows"] if r["team"] == 0]
                gd = [x["episode"]["goals_home"] - x["episode"]["goals_away"] for x in res]
                gen = sum(r["chosen_source"] != "library" for x in res for r in x["rows"] if r["team"] == 0)
                shots = sum(x["episode"]["shots_home"] for x in res)
                out.setdefault(who, {})[style] = {
                    "mean_play_reward": float(np.mean(rew)) if rew else 0.0, "goal_diff": float(np.sum(gd)),
                    "shots": int(shots), "generated_plays": int(gen), "plays": len(rew),
                    "held_out": style in self.lcfg["held_out_styles"],
                }
        out["beats_all_styles"] = all(
            out["main"][s]["mean_play_reward"] >= out["library"][s]["mean_play_reward"] for s in styles)
        self.final_eval = out
        self.save()
        return out

    def held_out_check(self, n: int = 6, workers: int = 4) -> dict[str, Any]:
        """Same games under the training and the held-out physics (spec §11 anti-exploit)."""
        base = load_config("sim")
        out = {}
        for name, cfg in (("train", base), ("held_out", held_out_sim(base))):
            rng = np.random.default_rng(99)
            jobs = []
            for k in range(n):
                sc = sample_scenario(rng, SCENARIO_TYPES[:-2] + ("random_open_play",))
                jobs.append({"episode_id": f"H-{name}-{k}", "seed": int(rng.integers(1 << 31)),
                             "scenario": sc.to_dict(), "home": self.spec("main"), "away": self.spec("library"),
                             "randomise": False, "sim_cfg": cfg})
            res = []
            run_jobs(jobs, None, workers=workers, on_result=res.append, progress_every=0)
            rew = [r["reward"] for x in res for r in x["rows"] if r["team"] == 0]
            out[name] = float(np.mean(rew)) if rew else 0.0
        drop = (out["train"] - out["held_out"]) / max(abs(out["train"]), 1e-3)
        out["relative_drop"] = drop
        out["flag"] = bool(drop > self.lcfg["held_out_drop_flag"])
        if out["flag"]:
            self.flags.append(f"update {self.update}: held-out EPV dropped {drop:.0%} — possible sim overfitting")
        out["update"] = self.update
        self.history.append({"update": self.update, "held_out": out})
        self.save()
        return out

    def regression_gate(self, workers: int = 4) -> dict[str, Any]:
        """Option 4 guardrail: the run's final generator vs the generator it started from.

        Same fixed games against every scripted style (held-out one included). If the final
        generator is meaningfully worse against any style, the gate fails and the next run
        will not continue from this run's generator (:func:`.runs.plan_start`).
        """
        n = int(self.lcfg.get("gate_games", 8))
        tol_abs = float(self.lcfg.get("gate_tolerance_abs", 0.002))
        tol_rel = float(self.lcfg.get("gate_tolerance_rel", 0.25))
        styles = list(self.lcfg["scripted_styles"])
        out: dict[str, Any] = {"styles": {}, "games_per_style": n}
        for style in styles:
            rng = np.random.default_rng(4242 + styles.index(style))
            base = []
            for k in range(n):
                sc = sample_scenario(rng, SCENARIO_TYPES[:-2] + ("random_open_play",))
                base.append({"seed": int(rng.integers(1 << 31)), "scenario": sc.to_dict(),
                             "away": self.spec(style), "randomise": False, "k": k})
            means = {}
            for who, file in (("start", "start.pt"), ("final", "main.pt")):
                spec = {**self.spec("main"), "id": f"gate_{who}", "generator_file": file, "activation": "on_gap",
                        "gen_temperature": 0.7}
                jobs = [{**{x: y for x, y in b.items() if x != "k"}, "episode_id": f"G-{who}-{style}-{b['k']}",
                         "home": spec} for b in base]
                res: list[dict] = []
                run_jobs(jobs, None, workers=workers, on_result=res.append, progress_every=0)
                rew = [r["reward"] for x in res for r in x["rows"] if r["team"] == 0]
                means[who] = float(np.mean(rew)) if rew else 0.0
            allowed = max(tol_abs, tol_rel * abs(means["start"]))
            ok = means["final"] >= means["start"] - allowed
            out["styles"][style] = {"start": means["start"], "final": means["final"],
                                    "diff": means["final"] - means["start"], "allowed_drop": allowed, "ok": bool(ok),
                                    "held_out": style in self.lcfg["held_out_styles"]}
        out["passed"] = all(v["ok"] for v in out["styles"].values())
        out["failed_styles"] = [k for k, v in out["styles"].items() if not v["ok"]]
        self.run_info["gate"] = out
        if not out["passed"]:
            self.flags.append(f"run {self.run}: regression gate failed against {', '.join(out['failed_styles'])}; "
                              "the next run will not continue from this generator")
        self.save()
        return out

    def save(self) -> None:
        self.archive.save(self.dir / "archive.json")
        self.state_path.write_text(json.dumps({
            "update": self.update, "snapshots": self.snapshots, "elo": self.elo.ratings,
            "payoff": self.payoff.to_json(), "history": self.history, "flags": self.flags,
            "final_eval": self.final_eval, **self.run_info,
        }, indent=1, default=str))


def run_league(models_dir: str | Path, data_root: str | Path, updates: int | None = None, profile: str | None = None,
               workers: int = 4, start_mode: str = "auto", run_dir: str | Path | None = None,
               promoted_root: str | Path | None = None) -> dict[str, Any]:
    """Create the next run (or resume ``run_dir``), train, check, evaluate and gate it.

    ``updates`` is the run's total; a resumed run only plays the updates it still lacks.
    """
    lg = League(models_dir, data_root, profile, run_dir=run_dir, start_mode=start_mode, promoted_root=promoted_root)
    ri = lg.run_info
    print(f"  run {ri['run']} (opponent pool {pool_label(lg.lcfg)}): starts from {ri['start_from']} "
          f"({ri['start_reason']}); archive seeded from runs {ri.get('seeded_from_runs') or 'none'}", flush=True)
    if ri.get("seeds_to_evaluate"):
        k = lg.evaluate_seeds(workers)
        print(f"  re-evaluated {k} archive seeds from a different opponent pool against "
              f"{', '.join(lg.styles)}", flush=True)
    n = updates or lg.tcfg["ppo"][lg.prof]["updates"]
    every = lg.lcfg["held_out_eval_every"]
    if lg.update:
        print(f"  resuming run {lg.run} at update {lg.update} of {n}", flush=True)
    for _ in range(max(0, n - lg.update)):
        rec = lg.run_update(workers)
        main = rec["ppo"]["main"]
        print(f"  update {rec['update']}: {rec['episodes']} games, main rollouts {main.get('n', 0)}, "
              f"mean generated-play reward {main.get('mean_reward', float('nan')):.4f}, "
              f"generated share {rec['main_generated_share']:.2f}, validity {rec['validity']:.3f}, "
              f"Elo main {rec['elo'].get('main', 0):.0f}, archive {rec['archive']}, {rec['wall_s']}s", flush=True)
        if lg.update % every == 0:
            print("  held-out check:", lg.held_out_check(workers=workers), flush=True)
    ho = lg.held_out_check(workers=workers)
    print("  held-out check:", ho, flush=True)
    ev = lg.evaluate(n=lg.lcfg.get("eval_games", 12), workers=workers)
    gate = lg.regression_gate(workers=workers)
    print(f"  regression gate: {'passed' if gate['passed'] else 'FAILED vs ' + ', '.join(gate['failed_styles'])}",
          flush=True)
    return {"run": lg.run, "dir": str(lg.dir), "continued_from": ri["continued_from"],
            "start_reason": ri["start_reason"], "updates": lg.update, "held_out": ho, "evaluation": ev,
            "gate": gate, "archive": lg.archive.coverage(), "elo": lg.elo.ratings, "flags": lg.flags}
