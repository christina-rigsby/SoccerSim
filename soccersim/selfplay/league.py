"""League training for the generator (spec §11 Phase C; M9).

Players:

- **main** — the learning agent; plays both sides with shared weights.
- **snapshots** — frozen copies of main every ``snapshot_every`` updates.
- **main exploiter** — trained only against the current main agent; reset to the Phase B
  generator every ``main_exploiter_reset_every`` updates.
- **league exploiter** — trained against the whole pool.
- **scripted styles** — library-only teams with fixed play weights; ``possession`` is held
  out of training entirely and only used for evaluation.

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
from .qd_archive import Archive, descriptor
from .runner import run_jobs

LEARNERS = ("main", "main_exploiter", "league_exploiter")
BAND_SCENARIOS = {"own_third": "mid_progression", "mid_own": "mid_progression", "mid_opp": "random_open_play",
                  "final_third": "final_third_attack"}


class League:
    def __init__(self, models_dir: str | Path, data_root: str | Path, profile: str | None = None,
                 seed: int = 0) -> None:
        self.models = Path(models_dir)
        self.dir = self.models / "league"
        self.root = Path(data_root)
        self.tcfg = load_config("training")
        self.prof = profile or self.tcfg["profile"]
        self.lcfg = load_config("league")
        self.rng = np.random.default_rng(seed)
        self.lib = load_library()
        self.dir.mkdir(parents=True, exist_ok=True)
        for f in ("critic.pt", "response.pt"):
            if (self.models / f).exists() and not (self.dir / f).exists():
                shutil.copy(self.models / f, self.dir / f)
        for name in ("main.pt", "ref.pt", "main_exploiter.pt", "league_exploiter.pt"):
            if not (self.dir / name).exists():
                shutil.copy(self.models / "generator.pt", self.dir / name)
        self.state_path = self.dir / "state.json"
        st = json.loads(self.state_path.read_text()) if self.state_path.exists() else {}
        self.update = st.get("update", 0)
        self.snapshots: list[str] = st.get("snapshots", [])
        self.elo = Elo(self.lcfg["elo_k"], self.lcfg["initial_elo"])
        self.elo.ratings = st.get("elo", {})
        self.payoff = Payoff.from_json(st.get("payoff", {}))
        self.history: list[dict] = st.get("history", [])
        self.flags: list[str] = st.get("flags", [])
        self.final_eval: dict = st.get("final_eval", {})
        min_evals = self.tcfg["qd"][f"min_evals_{self.prof}"]
        self.archive = Archive.load(self.dir / "archive.json", min_evals)
        self.styles = [s for s in self.lcfg["scripted_styles"] if s not in self.lcfg["held_out_styles"]]
        self.gens = {n: load_generator(self.dir / f"{n}.pt") for n in LEARNERS}
        self.ref = load_generator(self.dir / "ref.pt")
        self.critic = load_critic(self.dir / "critic.pt") if (self.dir / "critic.pt").exists() else None
        lr = self.tcfg["ppo"][self.prof]["lr"]
        self.opts = {n: torch.optim.Adam(self.gens[n].parameters(), lr=lr) for n in LEARNERS}
        self.gen_ident = play_ids(self.lib).index("generated")

    # -- specs -------------------------------------------------------------------------------

    def spec(self, pid: str) -> dict[str, Any]:
        if pid in self.lcfg["scripted_styles"]:
            return {"id": pid, "kind": "style", "style": pid, "temperature": 0.01}
        if pid == "library":
            return {"id": "library", "kind": "library", "temperature": 0.01}
        file = f"{pid}.pt" if pid in LEARNERS else f"{pid.replace('@', '_')}.pt"
        return {"id": pid, "kind": "agent", "checkpoint": str(self.dir), "generator_file": file,
                "activation": "always", "k": 4, "critic": True, "temperature": 0.01, "gen_temperature": 1.0,
                "learner": pid if pid in LEARNERS else None}

    def pool(self) -> list[str]:
        return ["main", *self.snapshots, "main_exploiter", "league_exploiter", *self.styles]

    def _job(self, a: str, b: str, k: int, tag: str) -> dict[str, Any]:
        sc = sample_scenario(self.rng, SCENARIO_TYPES[:-2] + ("random_open_play",), tuple(self.lcfg["formations"]))
        home, away = (a, b) if self.rng.random() < 0.5 else (b, a)
        return {"episode_id": f"L{self.update:03d}-{tag}-{k:03d}", "seed": int(self.rng.integers(1 << 31)),
                "scenario": sc.to_dict(), "home": self.spec(home), "away": self.spec(away), "randomise": True}

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
                rng = np.random.default_rng(1234)
                for k in range(n):
                    sc = sample_scenario(rng, SCENARIO_TYPES[:-2] + ("random_open_play",))
                    jobs.append({"episode_id": f"E-{who}-{style}-{k}", "seed": int(rng.integers(1 << 31)),
                                 "scenario": sc.to_dict(), "home": spec, "away": self.spec(style), "randomise": True})
                res = []
                run_jobs(jobs, None, workers=workers, on_result=res.append, progress_every=0)
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

    def save(self) -> None:
        self.archive.save(self.dir / "archive.json")
        self.state_path.write_text(json.dumps({
            "update": self.update, "snapshots": self.snapshots, "elo": self.elo.ratings,
            "payoff": self.payoff.to_json(), "history": self.history, "flags": self.flags,
            "final_eval": self.final_eval,
        }, indent=1, default=str))


def run_league(models_dir: str | Path, data_root: str | Path, updates: int | None = None, profile: str | None = None,
               workers: int = 4) -> dict[str, Any]:
    lg = League(models_dir, data_root, profile)
    n = updates or lg.tcfg["ppo"][lg.prof]["updates"]
    every = lg.lcfg["held_out_eval_every"]
    for _ in range(n):
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
    ev = lg.evaluate(n=max(4, lg.tcfg["ppo"][lg.prof]["episodes_per_update"] // 2), workers=workers)
    return {"updates": lg.update, "held_out": ho, "evaluation": ev, "archive": lg.archive.coverage(),
            "elo": lg.elo.ratings, "flags": lg.flags}
