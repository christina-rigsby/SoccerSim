"""A greedy role-filling stand-in — **not** the assignment solve.

§4 specifies that filling a play's roles is an assignment problem solved by bipartite
matching (Hungarian / Kuhn–Munkres) over capability-match edge weights (D-004). That
belongs with the graph and weight-algebra work, which is blocked on Q-001 and being built
elsewhere.

This is the placeholder that lets the rest of the pipeline run in the meantime: fill each
role with the best remaining candidate, hardest-to-fill role first. It is **demonstrably
suboptimal** — greedy assignment can strand a role whose only candidate was taken by an
earlier role that had alternatives, which is precisely why §4 calls for a real solve —
and it makes no use of any weight semantics, only M0.5's raw fit scores (D-022).

Replace :func:`greedy_assignment` with the real solve when it lands; everything
downstream takes a plain ``{role: player_id}`` mapping either way.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..constraints.roles import role_coverage
from ..domain.entities import Team
from ..domain.roles import get_role
from ..domain.state import GameState
from .play import Play


@dataclass
class AssignmentResult:
    """What the greedy pass managed to fill."""

    assignment: dict[str, int]
    unfilled: tuple[str, ...] = ()
    #: Roles that had candidates but lost all of them to earlier roles — the specific
    #: failure mode a real assignment solve would avoid.
    starved: tuple[str, ...] = ()

    @property
    def complete(self) -> bool:
        return not self.unfilled

    def describe(self) -> str:
        filled = ", ".join(f"{role}=#{pid}" for role, pid in sorted(self.assignment.items()))
        lines = [f"  {filled or '(nothing filled)'}"]
        if self.unfilled:
            lines.append(f"  unfilled: {', '.join(self.unfilled)}")
        if self.starved:
            lines.append(
                f"  starved by greedy order (a real solve may fill these): "
                f"{', '.join(self.starved)}"
            )
        return "\n".join(lines)


def greedy_assignment(
    play: Play, state: GameState, team: Team = Team.HOME
) -> AssignmentResult:
    """Fill ``play``'s roles greedily, scarcest role first.

    Ordering by coverage depth is what makes the greedy pass usable at all: filling the
    role with one eligible player before the role with eight avoids the obvious
    starvation. It does not avoid all of it.
    """
    players = state.team_state(team).available()
    coverage = {role: role_coverage(players, get_role(role)) for role in play.roles()}

    assignment: dict[str, int] = {}
    unfilled: list[str] = []
    starved: list[str] = []
    taken: set[int] = set()

    for role in sorted(play.roles(), key=lambda r: coverage[r].depth):
        candidates = [fit for fit in coverage[role].candidates if fit.player_id not in taken]
        if not candidates:
            unfilled.append(role)
            if coverage[role].candidates:
                starved.append(role)
            continue
        # Prefer a player who has practised the role, then raw fit — §5's
        # `role_familiarity` as a tie-break, pending its real soft-constraint form.
        best = max(candidates, key=lambda fit: (fit.practised, fit.score))
        assignment[role] = best.player_id
        taken.add(best.player_id)

    return AssignmentResult(
        assignment=assignment,
        unfilled=tuple(unfilled),
        starved=tuple(starved),
    )
