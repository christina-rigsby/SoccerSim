# Generated and promoted plays

Plays written by the Module 3 generator during league self-play that beat the library
median in their niche against every scripted opponent style (spec §11 promotion
pipeline). Each league run gets its own folder, `run_<N>/`, numbered in the order the
runs promoted plays; `provenance.run` in every file repeats the number.

| Run | League directory | Notes |
|---|---|---|
| `run_1` | `data/models/league_run1/` | first quick-profile league |
| `run_2` | `data/models/league/` | after the finishing-step mutation and exploration changes; the run shown in the self-play report |

Every file is **pending human review**. Nothing here is loaded into the play library;
move a play into `plays/offensive/` only after checking it.

`python scripts/selfplay.py promote` writes the next run's folder. Re-running it for the
same league rewrites that league's folder instead of creating a new one.
