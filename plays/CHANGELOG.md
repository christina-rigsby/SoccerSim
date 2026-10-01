# Play library changelog

Changes to the starter library (spec §6) and the reason for each. Spec §4.6: when a
starter play conflicts with the schema, fix the play and record it here.

## v1 (initial import)

All twelve starter plays from spec §6.1–6.12 were imported verbatim and validate against
the schema without modification. Points of interpretation, all implemented in code rather
than by editing the plays:

- `lane_open.from` accepts a role id or `ball_holder` (spec note under §6.6).
- A step whose steps run out without the play's `success` predicate holding ends with
  the extra end reason `completed` (spec §5 lists no reason for this case).
- Movement targets anchored on `ball`, `ball_holder` or the mover's own role are
  resolved once when the action is issued, so `carry: {anchor: ball, offset: [3, -5]}`
  is a fixed destination rather than one that moves with the carrier (see D-039).
