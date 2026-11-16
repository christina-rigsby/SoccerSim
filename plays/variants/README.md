# Play variants

Candidate changes to the play library, tried by one team in evaluation before anything joins
the library (`scripts/evaluate_teams.py --teams library library+branchy ...`). A variant is a
folder here: its plays are added to the library, replacing any library play with the same id,
and the ids listed in its `_remove.txt` are removed. Variants stack: `library+branchy+defensive_plus`.

- `defensive_plus/` — four new defensive plays: delay and recover after losing the ball in our
  half, doubling up on a winger, defending a cross, pressing a central build-up.
- `branchy/` — shorter versions of the five attacking plays that almost never completed
  (one-two, third-man combination, wide overlap, through ball, switch of play), with a
  fallback in every step instead of waiting and timing out (Q-038).
- `prune_failing/` — removes four promoted generated plays that are called often but almost
  never complete.

A variant that wins is adopted by moving its plays into `plays/offensive/` or `plays/defensive/`
(a pool change: bump `pool_version`).
