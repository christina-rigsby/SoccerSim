"""Play roles — the design doc's ``RoleRequirement``, and how players are matched to it.

A :class:`PlayRole` is a job a play needs someone to do ("overlap runner", "target
forward"), as distinct from the formation slot a player lines up in
(:class:`~soccersim.domain.entities.PositionalRole`). Keeping them separate is what lets
a play say "I need someone who can overlap and cross" and have a RB, RM or RCM answer
(D-018).

Each role carries two things, and they do different jobs:

**Weights** — which attributes matter and how much. These produce a continuous fit score
in ``[0, 1]``. The fit score is *deliberately not* a cost, a utility, or a probability:
the weight algebra is still unresolved (Q-001), and turning fit into an edge weight
before that is settled would bake in a semantics through the back door. So fit stays a
raw, unitless quality reading, and the Hungarian cost matrix is built from it later
(D-022).

**Minimums** — the specialist bar. This drives §5's hard ``min_role_coverage``
constraint: "if a play requires a specialist role and no player meets the minimum
capability threshold, the play is infeasible regardless of assignment cost". Because
minimums are per-attribute rather than a threshold on the fit score, the hard check
needs no weight semantics at all and is available now (D-020).

Minimums are authored in each attribute's native units — 0–100 for attributes, SI for
physical — and compared on the normalised scale, so attributes where lower is better
(``reaction_time``) invert automatically and "meets the minimum" always means "is at
least this good".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

import numpy as np

from .attributes import (
    ATTRIBUTE_MAX,
    PHYSICAL_NAMES,
    PHYSICAL_RANGES,
    Attributes,
    normalised_physical,
)
from .entities import CapabilityProfile, PlayerState, PositionalRole

# Physical archetypes by slot, in SI units. Used as roster defaults so a roster only has
# to state physical values where a player departs from their positional norm.
QUICK = CapabilityProfile(max_speed=8.6, max_accel=7.0)
AVERAGE = CapabilityProfile(max_speed=7.8, max_accel=6.5)
STRONG = CapabilityProfile(max_speed=7.2, max_accel=5.8)
KEEPER = CapabilityProfile(max_speed=6.8, max_accel=5.5, reaction_time=0.25)

ARCHETYPE_CAPABILITY: dict[PositionalRole, CapabilityProfile] = {
    PositionalRole.GK: KEEPER,
    PositionalRole.CB: STRONG,
    PositionalRole.LCB: STRONG,
    PositionalRole.RCB: STRONG,
    PositionalRole.LB: QUICK,
    PositionalRole.RB: QUICK,
    PositionalRole.LM: QUICK,
    PositionalRole.RM: QUICK,
    PositionalRole.LW: QUICK,
    PositionalRole.RW: QUICK,
}


def archetype_capability(slot: PositionalRole) -> CapabilityProfile:
    """Default physical profile for a positional slot."""
    return ARCHETYPE_CAPABILITY.get(slot, AVERAGE)


def _normalise_name(name: str, value: float) -> float:
    """Project a native-unit value for ``name`` onto 0–1, higher always better."""
    if name in PHYSICAL_NAMES:
        return normalised_physical(name, value)
    return float(np.clip(value / ATTRIBUTE_MAX, 0.0, 1.0))


@dataclass(frozen=True)
class PlayRole:
    """One job within a play, and what it takes to do it well."""

    key: str
    label: str
    description: str
    #: Attribute or physical name -> relative importance. Normalised to sum to 1.
    weights: Mapping[str, float]
    #: Attribute or physical name -> specialist floor, in native units. Sparse: only
    #: where a genuine bar exists, because every minimum can make a play infeasible.
    minimums: Mapping[str, float] = field(default_factory=dict)
    #: Slots that typically fill this role. Advisory only — never enforced, since the
    #: whole point of separating play roles from slots is that the match is by
    #: capability, not by label. A holding midfielder outscoring a centre-back at
    #: ``ball_playing_defender`` is the model working, not a bug.
    affinities: frozenset[PositionalRole] = frozenset()
    #: Slots that are *permitted* to fill this role, as a hard gate. Empty means any.
    #:
    #: Reserved for roles where exclusivity is a rule of the game rather than a
    #: tactical preference — in practice only the goalkeeper. Without it, an outfielder
    #: with good passing and positioning outscores the actual keeper at
    #: ``sweeper_keeper``, which the attribute minimums cannot prevent because the
    #: shortfall is not in any attribute.
    required_slots: frozenset[PositionalRole] = frozenset()

    def __post_init__(self) -> None:
        if not self.weights:
            raise ValueError(f"role {self.key!r} has no weights")
        for name, weight in self.weights.items():
            _check_known(self.key, name)
            if weight <= 0:
                raise ValueError(
                    f"role {self.key!r} weight for {name!r} is {weight}; weights must "
                    "be positive (a zero-weight attribute should just be omitted)"
                )
        for name, minimum in self.minimums.items():
            _check_known(self.key, name)
            _check_minimum_in_range(self.key, name, minimum)
        object.__setattr__(self, "weights", dict(self.weights))
        object.__setattr__(self, "minimums", dict(self.minimums))
        object.__setattr__(self, "affinities", frozenset(self.affinities))
        object.__setattr__(self, "required_slots", frozenset(self.required_slots))

    def permits_slot(self, slot: PositionalRole) -> bool:
        """Whether ``slot`` is allowed to fill this role at all."""
        return not self.required_slots or slot in self.required_slots

    @property
    def normalised_weights(self) -> dict[str, float]:
        """Weights scaled to sum to 1, so fit is comparable across roles."""
        total = float(sum(self.weights.values()))
        return {name: weight / total for name, weight in self.weights.items()}

    @property
    def inputs(self) -> tuple[str, ...]:
        """Every name this role reads, weighted or gated."""
        return tuple(dict.fromkeys([*self.weights, *self.minimums]))


def _check_known(role_key: str, name: str) -> None:
    if name in PHYSICAL_NAMES or name in Attributes.names():
        return
    raise ValueError(
        f"role {role_key!r} references unknown attribute {name!r}. Known attributes: "
        f"{', '.join(Attributes.names())}. Known physical: "
        f"{', '.join(sorted(PHYSICAL_NAMES))}."
    )


def _check_minimum_in_range(role_key: str, name: str, minimum: float) -> None:
    """Reject a minimum outside its scale.

    Without this, a physical minimum above the reference ceiling would normalise to 1.0
    by clipping — and so would every player's value, silently passing everyone.
    """
    if name in PHYSICAL_NAMES:
        low, high = PHYSICAL_RANGES[name]
        lo, hi = min(low, high), max(low, high)
        if not lo <= minimum <= hi:
            raise ValueError(
                f"role {role_key!r} minimum for {name!r} is {minimum}, outside the "
                f"reference range {lo}–{hi}; a minimum beyond the range clips and "
                "would pass every player"
            )
    elif not 0.0 <= minimum <= ATTRIBUTE_MAX:
        raise ValueError(
            f"role {role_key!r} minimum for {name!r} is {minimum}, outside the "
            f"0–{ATTRIBUTE_MAX:.0f} attribute scale"
        )


@dataclass(frozen=True)
class RoleFit:
    """How well one player suits one role, and why.

    ``score`` is a unitless quality reading in ``[0, 1]``, **not** a cost, a utility or
    a probability (D-022 / Q-001). ``contributions`` and ``unmet`` exist so a poor fit
    can be explained rather than just reported — which matters a lot when hand-authoring
    a roster and wondering why nobody can play a role.
    """

    player_id: int
    role_key: str
    score: float
    #: Name -> its share of the final score. Sums to ``score``.
    contributions: dict[str, float]
    #: Name -> (actual, required) in native units, for each minimum not met.
    unmet: dict[str, tuple[float, float]]
    practised: bool
    #: True when the role restricts which slots may fill it and this player's does not
    #: qualify. Tracked separately from ``unmet`` because it is not an attribute
    #: shortfall and no amount of improvement fixes it.
    slot_ineligible: bool = False

    @property
    def meets_minimums(self) -> bool:
        """Whether this player clears the role's bar — attributes and slot alike."""
        return not self.unmet and not self.slot_ineligible

    @property
    def limiting_factor(self) -> str | None:
        """The weighted input contributing least relative to its weight.

        The attribute to improve first, or the reason a fit is mediocre.
        """
        if not self.contributions:
            return None
        return min(self.contributions, key=self.contributions.get)

    def explain(self) -> str:
        parts = [f"{self.role_key}: {self.score:.3f}"]
        if self.slot_ineligible:
            parts.append("WRONG SLOT")
        if self.unmet:
            failures = ", ".join(
                f"{name} {actual:g} < {required:g}"
                for name, (actual, required) in sorted(self.unmet.items())
            )
            parts.append(f"BELOW MINIMUM ({failures})")
        if not self.practised:
            parts.append("not practised")
        return "  ".join(parts)


def resolve_input(player: PlayerState, name: str) -> tuple[float, float]:
    """``(native_value, normalised_value)`` of ``name`` for ``player``.

    Physical names resolve against *fatigue-degraded* capability, extending D-006 into
    role matching: a tired player is genuinely worse at a pace-dependent role, and the
    same degradation that slows their arrival times should lower their fit. Technical
    attributes are not degraded — fatigue is modelled as a physical effect only, which
    is a simplification worth knowing about (Q-021).
    """
    if name in PHYSICAL_NAMES:
        native = float(getattr(player.effective_capability(), name))
    else:
        native = player.require_attributes().get(name)
    return native, _normalise_name(name, native)


def role_fit(player: PlayerState, role: PlayRole) -> RoleFit:
    """Score ``player`` for ``role``.

    Raises if the player has no attributes, since an inferred-attribute opponent cannot
    be matched to a role yet (Q-008).
    """
    contributions: dict[str, float] = {}
    for name, weight in role.normalised_weights.items():
        _, normalised = resolve_input(player, name)
        contributions[name] = weight * normalised

    unmet: dict[str, tuple[float, float]] = {}
    for name, minimum in role.minimums.items():
        native, normalised = resolve_input(player, name)
        if normalised < _normalise_name(name, minimum) - 1e-12:
            unmet[name] = (native, float(minimum))

    return RoleFit(
        player_id=player.player_id,
        role_key=role.key,
        score=float(sum(contributions.values())),
        contributions=contributions,
        unmet=unmet,
        practised=player.has_practised(role.key),
        slot_ineligible=not role.permits_slot(player.positional_role),
    )


# ---------------------------------------------------------------------------
# The role catalogue
#
# One role per job that the design doc's named plays (§3) actually require. Each is
# annotated with the play that needs it, so an unused role is visible as such and the
# catalogue does not quietly accumulate roles nothing asks for.
# ---------------------------------------------------------------------------

ROLE_CATALOGUE: dict[str, PlayRole] = {
    role.key: role
    for role in (
        PlayRole(
            key="sweeper_keeper",
            label="Sweeper keeper",
            description="Starts possession buildup from the back; sweeps behind a high line.",
            weights={
                "passing_short": 0.35,
                "passing_long": 0.20,
                "positioning": 0.30,
                "reaction_time": 0.15,
            },
            minimums={"passing_short": 45.0},
            affinities=frozenset({PositionalRole.GK}),
            required_slots=frozenset({PositionalRole.GK}),
        ),
        PlayRole(
            key="ball_playing_defender",
            label="Ball-playing defender",
            description="Defends the line and breaks pressure with the first pass.",
            weights={
                "passing_short": 0.30,
                "positioning": 0.25,
                "marking": 0.20,
                "tackling": 0.15,
                "strength": 0.10,
            },
            minimums={"marking": 45.0},
            affinities=frozenset(
                {PositionalRole.CB, PositionalRole.LCB, PositionalRole.RCB}
            ),
        ),
        PlayRole(
            key="overlap_runner",
            label="Overlap runner",
            description=(
                "Runs outside the winger and delivers from the byline. The Overlap play "
                "(§3, wing overload) is built around this role."
            ),
            weights={
                "crossing": 0.30,
                "work_rate": 0.25,
                "max_speed": 0.25,
                "max_accel": 0.10,
                "first_touch": 0.10,
            },
            # A player who cannot repeat the run, or cannot get there, cannot do this
            # job at all — the distinction §5 draws between "filled but poorly matched"
            # and infeasible.
            minimums={"max_speed": 7.6, "work_rate": 60.0},
            affinities=frozenset(
                {PositionalRole.LB, PositionalRole.RB, PositionalRole.LM, PositionalRole.RM}
            ),
        ),
        PlayRole(
            key="underlap_runner",
            label="Underlap runner",
            description="Runs the inside channel while the winger holds width (§3, Underlap).",
            weights={
                "work_rate": 0.25,
                "max_accel": 0.25,
                "first_touch": 0.20,
                "passing_short": 0.15,
                "max_speed": 0.15,
            },
            minimums={"work_rate": 58.0},
            affinities=frozenset(
                {PositionalRole.LB, PositionalRole.RB, PositionalRole.LCM, PositionalRole.RCM}
            ),
        ),
        PlayRole(
            key="wide_creator",
            label="Wide creator",
            description="Holds width, beats a defender, crosses or cuts back.",
            weights={
                "dribbling": 0.30,
                "crossing": 0.28,
                "first_touch": 0.15,
                "max_accel": 0.15,
                "passing_short": 0.12,
            },
            minimums={"dribbling": 50.0},
            affinities=frozenset(
                {PositionalRole.LW, PositionalRole.RW, PositionalRole.LM, PositionalRole.RM}
            ),
        ),
        PlayRole(
            key="inverted_winger",
            label="Inverted winger",
            description=(
                "Cuts inside off the flank onto their stronger foot to shoot. Needs a "
                "genuine opposite foot, which is why weak_foot is gated rather than "
                "merely weighted."
            ),
            weights={
                "dribbling": 0.30,
                "finishing": 0.22,
                "weak_foot": 0.18,
                "first_touch": 0.15,
                "max_accel": 0.15,
            },
            minimums={"weak_foot": 55.0, "dribbling": 50.0},
            affinities=frozenset({PositionalRole.LW, PositionalRole.RW}),
        ),
        PlayRole(
            key="target_forward",
            label="Target forward",
            description="Receives and holds the long ball (§3, direct/long-ball strategy).",
            weights={
                "strength": 0.30,
                "heading": 0.28,
                "first_touch": 0.24,
                "finishing": 0.18,
            },
            minimums={"strength": 58.0, "heading": 58.0},
            affinities=frozenset({PositionalRole.ST, PositionalRole.CF}),
        ),
        PlayRole(
            key="runner_in_behind",
            label="Runner in behind",
            description=(
                "Attacks the space behind the last defender (§3, direct vertical "
                "counter). The one role where raw pace is non-negotiable."
            ),
            weights={
                "max_speed": 0.35,
                "finishing": 0.25,
                "positioning": 0.20,
                "max_accel": 0.20,
            },
            minimums={"max_speed": 8.0},
            affinities=frozenset(
                {PositionalRole.ST, PositionalRole.CF, PositionalRole.LW, PositionalRole.RW}
            ),
        ),
        PlayRole(
            key="deep_lying_passer",
            label="Deep-lying passer",
            description="Switches play and hits the long outlet (§3, switch-and-cross).",
            weights={
                "passing_long": 0.35,
                "passing_short": 0.28,
                "positioning": 0.22,
                "first_touch": 0.15,
            },
            minimums={"passing_long": 58.0},
            affinities=frozenset(
                {PositionalRole.CDM, PositionalRole.CM, PositionalRole.LCM, PositionalRole.RCM}
            ),
        ),
        PlayRole(
            key="ball_winner",
            label="Ball winner",
            description="Wins the ball back to start a counter (§3, 3-pass counter).",
            weights={
                "tackling": 0.30,
                "work_rate": 0.25,
                "positioning": 0.25,
                "strength": 0.20,
            },
            minimums={"tackling": 55.0},
            affinities=frozenset(
                {PositionalRole.CDM, PositionalRole.CM, PositionalRole.LCM, PositionalRole.RCM}
            ),
        ),
        PlayRole(
            key="box_target",
            label="Box target",
            description="Attacks the cross at the near or far post (§3, wing overload).",
            weights={
                "heading": 0.35,
                "positioning": 0.28,
                "strength": 0.20,
                "finishing": 0.17,
            },
            minimums={"heading": 52.0},
            affinities=frozenset(
                {PositionalRole.ST, PositionalRole.CF, PositionalRole.LW, PositionalRole.RW}
            ),
        ),
        PlayRole(
            key="first_presser",
            label="First presser",
            description="Initiates the press and sets the trap (§3, high press).",
            weights={
                "work_rate": 0.35,
                "max_speed": 0.25,
                "tackling": 0.20,
                "positioning": 0.20,
            },
            minimums={"work_rate": 65.0},
            affinities=frozenset(
                {PositionalRole.ST, PositionalRole.CF, PositionalRole.LW, PositionalRole.RW}
            ),
        ),
    )
}


def get_role(key: str) -> PlayRole:
    """Look up a role, listing the catalogue if the key is unknown."""
    try:
        return ROLE_CATALOGUE[key]
    except KeyError:
        raise KeyError(
            f"unknown play role {key!r}; catalogue is "
            f"{', '.join(sorted(ROLE_CATALOGUE))}"
        ) from None


def rank_players(players, role: PlayRole, eligible_only: bool = True) -> list[RoleFit]:
    """Every player scored for ``role``, best first.

    With ``eligible_only`` (the default) players who fail a minimum or are unavailable
    are dropped, matching what ``min_role_coverage`` and ``eligibility`` would prune.
    Pass ``False`` to see near-misses, which is what you want when tuning a roster.
    """
    fits = []
    for player in players:
        if eligible_only and not player.available:
            continue
        fit = role_fit(player, role)
        if eligible_only and not fit.meets_minimums:
            continue
        fits.append(fit)
    return sorted(fits, key=lambda fit: fit.score, reverse=True)
