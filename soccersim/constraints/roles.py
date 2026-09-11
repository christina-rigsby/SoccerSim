"""Role-based hard constraints — §5's ``eligibility`` and ``min_role_coverage``.

Both are **hard** by the design doc's own test (*is violating this ever acceptable if
the alternative is worse?*): you cannot field a suspended player at all, and a play
requiring a specialist nobody can be is not a bad play, it is an impossible one. So both
prune before any scoring happens (D-005).

Crucially neither needs the weight algebra (Q-001). ``min_role_coverage`` is expressed as
per-attribute minimums rather than as a threshold on the fit score, so "is this play
even possible with this squad" is answerable now, while "which of these players should
take the role" waits for M1's cost matrix (D-020).

§5 is explicit that the two halves are different: coverage is "no player meets the
minimum capability threshold... regardless of assignment cost", which is "distinct from
'role filled but poorly matched,' which is soft".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence

from ..domain.entities import PlayerState
from ..domain.roles import PlayRole, RoleFit, get_role, role_fit
from .feasibility import Violation


def check_eligibility(player: PlayerState, role: PlayRole) -> Violation | None:
    """``eligibility`` (§5): an unavailable player cannot fill a required role."""
    if player.available:
        return None
    return Violation(
        "eligibility",
        f"player {player.label} is unavailable (injured, suspended or sent off) and "
        f"cannot fill role {role.key!r}",
    )


@dataclass
class RoleCoverage:
    """Who, if anyone, can fill one role — and how narrowly."""

    role: PlayRole
    #: Available players clearing every minimum, best fit first.
    candidates: list[RoleFit] = field(default_factory=list)
    #: Available players who failed at least one minimum, best fit first. Kept because
    #: a near-miss is the useful diagnostic when a play is infeasible: "nobody can do
    #: this" is far less actionable than "your quickest forward is 0.1 m/s short".
    near_misses: list[RoleFit] = field(default_factory=list)

    @property
    def is_covered(self) -> bool:
        return bool(self.candidates)

    @property
    def best(self) -> RoleFit | None:
        return self.candidates[0] if self.candidates else None

    @property
    def depth(self) -> int:
        """How many players could fill this role.

        Depth of 1 is worth noticing: the role is covered, but losing that player to
        fatigue or a card makes every play requiring it infeasible at once.
        """
        return len(self.candidates)

    def closest_miss(self) -> RoleFit | None:
        """The near-miss failing by the least, for diagnosing an uncovered role.

        Ranked by worst relative shortfall, so "0.1 m/s short of 8.0" beats "20 points
        short of 60". Players who fail only on slot eligibility are skipped: no margin
        describes them, and no improvement would qualify them.
        """
        measurable = [fit for fit in self.near_misses if fit.unmet]
        if not measurable:
            return None
        return min(
            measurable,
            key=lambda fit: max(
                abs(required - actual) / max(abs(required), 1e-9)
                for actual, required in fit.unmet.values()
            ),
        )


def role_coverage(players: Iterable[PlayerState], role: PlayRole) -> RoleCoverage:
    """Assess a squad against one role.

    Unavailable players are excluded entirely rather than listed as near-misses — being
    suspended is not a capability shortfall, and conflating the two would make the
    diagnostic misleading.
    """
    coverage = RoleCoverage(role=role)
    for player in players:
        if not player.available:
            continue
        fit = role_fit(player, role)
        if fit.meets_minimums:
            coverage.candidates.append(fit)
        else:
            coverage.near_misses.append(fit)
    coverage.candidates.sort(key=lambda fit: fit.score, reverse=True)
    coverage.near_misses.sort(key=lambda fit: fit.score, reverse=True)
    return coverage


def check_min_role_coverage(
    players: Iterable[PlayerState], role: PlayRole
) -> Violation | None:
    """``min_role_coverage`` (§5): no available player clears the role's minimums.

    The violation message names the closest near-miss and by what margin, because that
    is the difference between an actionable report and a dead end.
    """
    coverage = role_coverage(players, role)
    if coverage.is_covered:
        return None

    detail = f"no available player meets the minimums for role {role.key!r}"
    closest = coverage.closest_miss()
    if closest is not None:
        shortfalls = ", ".join(
            f"{name} {actual:g} (needs {required:g})"
            for name, (actual, required) in sorted(closest.unmet.items())
        )
        detail += f"; closest is player {closest.player_id} short on {shortfalls}"
    return Violation("min_role_coverage", detail)


def check_role_requirements(
    players: Sequence[PlayerState], role_keys: Iterable[str]
) -> list[Violation]:
    """Run coverage over every role a play requires, collecting all failures.

    Returns every uncovered role rather than stopping at the first, so authoring a play
    tells you the whole story at once — the same choice
    :func:`~soccersim.constraints.feasibility.check_waypoints` makes.

    Also catches the case where a play needs more distinct roles than there are
    available players, which is §5's ``player_count`` constraint in the form the role
    layer can already check.
    """
    keys = list(dict.fromkeys(role_keys))
    violations: list[Violation] = []

    available = [player for player in players if player.available]
    if len(keys) > len(available):
        violations.append(
            Violation(
                "player_count",
                f"play requires {len(keys)} distinct roles but only "
                f"{len(available)} players are available",
            )
        )

    for key in keys:
        role = get_role(key)
        if (found := check_min_role_coverage(available, role)) is not None:
            violations.append(found)
    return violations


def squad_coverage(
    players: Iterable[PlayerState], role_keys: Iterable[str] | None = None
) -> dict[str, RoleCoverage]:
    """Coverage for every role in the catalogue (or a named subset).

    The squad-level view: which roles this group of players can field, how deep, and
    where a single absence would leave a hole.
    """
    from ..domain.roles import ROLE_CATALOGUE

    players = list(players)
    keys = list(role_keys) if role_keys is not None else sorted(ROLE_CATALOGUE)
    return {key: role_coverage(players, get_role(key)) for key in keys}
