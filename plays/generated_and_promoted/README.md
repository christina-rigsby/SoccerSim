# Generated and promoted plays

Plays written by the Module 3 generator during league self-play that beat the library
median in their niche against every scripted opponent style (spec §11 promotion
pipeline). Each league run has its own folder, `run_<N>/`, matching its model directory
`data/models/runs/run_<N>/`; `provenance.run` in every file repeats the number.

Later runs build on these plays (D-044): they are mutated and imitated when the generator
is pretrained, and they seed the next run's archive, so a new play is only promoted if it
beats them in their niche. Each promoted play records `closest_earlier_promoted` (the most
similar earlier promoted play, if any) and `continued_from_run` (the run whose generator
its run continued training). Mutants of earlier promoted plays record `parent_run`.

| Run | Started from | Notes |
|---|---|---|
| `run_1` | pretrained generator | first quick-profile league |
| `run_2` | pretrained generator | after the finishing-step mutation and exploration changes |
| `run_3` | pretrained generator (pool v2) | first run on opponent pool v2 and the 29-play library; not in the library (pool v2 adopts runs 1-2 only) |

Every file is **pending human review**. Nothing here is loaded into the play library;
move a play into `plays/offensive/` only after checking it.

`python scripts/selfplay.py league` trains the next run; `python scripts/selfplay.py
promote` writes its folder (re-running promote for the same run rewrites that folder).

## Used as library plays

The runs listed in `configs/library.yaml` (`promoted_runs`) are loaded straight from these
folders into the play library, alongside the hand-written plays in `plays/offensive/` and
`plays/defensive/`. Nothing is copied or moved. When loaded, each play is restricted to the
archive niche it was promoted in (its start band and lane) and gets a cooldown of at least
8 s; the files here are not changed (D-046). Adding a run to that list changes the opponent
pool, so it starts a new run lineage.
