"""Marking-scheme inference — man-to-man or zonal, and who is marking whom.

§2 wants "inferred marking scheme: man-to-man vs. zonal, with zone boundaries if
zonal". Neither is observable directly; both have to be inferred from how defenders move
(Q-008).

Two signals per defender, over the observed frames:

**Target stability** — is the nearest attacker consistently the *same* attacker? A
man-marker's nearest opponent barely changes; a zonal defender's changes constantly as
attackers rotate through the zone.

**Displacement alignment** — when that attacker moves, does the defender move with them?
Stability alone is not enough: a zonal defender whose zone happens to contain one
stationary attacker also looks stable. Only when the attacker *moves* does the defender's
response reveal which scheme they are playing, so frames where the target barely moved
are skipped entirely rather than counted as evidence either way.

**Distance proximity and steadiness** — is the defender actually *near* their man, and
does that separation stay put? This turned out to be indispensable. Alignment alone
cannot separate a man-marker from a zonal defender *sliding across with the ball*: both
move nearly parallel to the ball carrier, so the zonal side got misread as mixed
marking. What distinguishes them is separation — a marker holds a couple of metres
and keeps holding it, while a zonal defender's distance to any given attacker swings
freely as attackers rotate through. Being close to your man is close to the definition
of marking them, so gating on it is principled rather than a patch.

Zone estimates fall out for free: a defender's mean position and its spread over the
window *is* the zone they are holding. Meaningless for a man-marker, but harmless, and
§2 asks for zone boundaries when the answer is zonal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import numpy as np

from ..domain.entities import Team
from ..domain.state import GameState
from .estimate import (
    DEFAULT_HALF_LIFE,
    DecayingMean,
    DecayingTally,
    Estimate,
    cosine_similarity,
)
from .observer import MatchObserver

#: A defender's nearest attacker must be the same one this often to look like a marker.
STABILITY_THRESHOLD = 0.60

#: And they must move with them at least this consistently (cosine similarity).
ALIGNMENT_THRESHOLD = 0.45

#: Beyond this mean separation a defender is covering, not marking.
MARKING_RADIUS = 8.0  # metres

#: And the separation has to be *held*: mean absolute deviation below this. A defender
#: whose distance to an attacker swings by more than a few metres is not tracking them.
MARKING_DISTANCE_VARIATION = 3.5  # metres

#: Frames where the target moved less than this tell us nothing — the defender had
#: nothing to track — so they are not observed at all.
MIN_DISPLACEMENT = 0.15  # metres

#: Share of defenders that must agree before the team is called man or zonal outright.
SCHEME_MAJORITY = 0.60

#: Effective observations before a per-defender verdict or the team scheme is actionable.
DEFENDER_MATURITY = 20.0
SCHEME_MATURITY = 6.0


class MarkingScheme(Enum):
    MAN = "man"
    ZONAL = "zonal"
    MIXED = "mixed"


@dataclass
class DefenderMarking:
    """Accumulated marking evidence for one defender."""

    defender_id: int
    targets: DecayingTally
    alignment: DecayingMean
    position_x: DecayingMean
    position_y: DecayingMean
    spread: DecayingMean
    #: Separation from the nearest attacker, and how much it moves around.
    distance: DecayingMean
    distance_variation: DecayingMean

    def target(self, clock: float) -> tuple[int, float] | None:
        """Most-tracked attacker and the share of frames they accounted for."""
        leader = self.targets.leader(clock)
        if leader is None:
            return None
        return int(leader[0]), leader[1]

    def scheme(self, clock: float) -> MarkingScheme | None:
        """This defender's apparent scheme, or ``None`` with no usable evidence.

        All four conditions must hold for ``MAN``: a consistent target, movement
        aligned with them, close enough to be marking, and a separation that is
        actually held steady.
        """
        target = self.target(clock)
        alignment = self.alignment.mean
        distance = self.distance.mean
        variation = self.distance_variation.mean
        if target is None or alignment is None or distance is None:
            return None
        man = (
            target[1] >= STABILITY_THRESHOLD
            and alignment >= ALIGNMENT_THRESHOLD
            and distance <= MARKING_RADIUS
            and (variation is None or variation <= MARKING_DISTANCE_VARIATION)
        )
        return MarkingScheme.MAN if man else MarkingScheme.ZONAL

    def zone(self, clock: float) -> tuple[np.ndarray, float] | None:
        """Zone centre and radius, as the mean position and its spread.

        Reported regardless of scheme — for a man-marker it simply describes where they
        happened to spend the window, which is why callers should check
        :meth:`scheme` first.
        """
        x, y, spread = self.position_x.mean, self.position_y.mean, self.spread.mean
        if x is None or y is None:
            return None
        return np.array([x, y]), float(spread or 0.0)

    def estimate(self, clock: float) -> Estimate[MarkingScheme]:
        target = self.target(clock)
        return Estimate(
            value=self.scheme(clock),
            observations=self.targets.total_at(clock),
            maturity_threshold=DEFENDER_MATURITY,
            updated_at=clock,
            detail={
                "target_id": target[0] if target else None,
                "target_stability": target[1] if target else 0.0,
                "alignment": self.alignment.mean,
                "distance": self.distance.mean,
                "distance_variation": self.distance_variation.mean,
            },
        )


class MarkingModel:
    """Infers how ``subject`` marks, from observed movement."""

    def __init__(self, subject: Team, half_life: float = DEFAULT_HALF_LIFE) -> None:
        self.subject = subject
        self.half_life = float(half_life)
        self.defenders: dict[int, DefenderMarking] = {}
        self._verdicts = DecayingTally(half_life)

    def _defender(self, defender_id: int) -> DefenderMarking:
        if defender_id not in self.defenders:
            self.defenders[defender_id] = DefenderMarking(
                defender_id=defender_id,
                targets=DecayingTally(self.half_life),
                alignment=DecayingMean(self.half_life),
                position_x=DecayingMean(self.half_life),
                position_y=DecayingMean(self.half_life),
                spread=DecayingMean(self.half_life),
                distance=DecayingMean(self.half_life),
                distance_variation=DecayingMean(self.half_life),
            )
        return self.defenders[defender_id]

    def observe(self, state: GameState, observer: MatchObserver) -> None:
        """Take one frame of evidence.

        Needs the observer for frame-to-frame displacement — the whole signal is in how
        positions *changed*, which a single snapshot cannot express.
        """
        clock = float(state.clock_seconds)
        defenders = state.team_state(self.subject).available()
        attackers = state.opponents_of(self.subject).available()
        if not defenders or not attackers:
            return

        attacker_positions = np.stack([a.position for a in attackers])

        for defender in defenders:
            record = self._defender(defender.player_id)
            record.position_x.observe(float(defender.position[0]), clock)
            record.position_y.observe(float(defender.position[1]), clock)

            distances = np.linalg.norm(attacker_positions - defender.position, axis=1)
            closest = int(np.argmin(distances))
            nearest = attackers[closest]
            record.targets.observe(nearest.player_id, clock)

            separation = float(distances[closest])
            running = record.distance.mean
            record.distance.observe(separation, clock)
            if running is not None:
                record.distance_variation.observe(abs(separation - running), clock)

            centre = record.zone(clock)
            if centre is not None:
                record.spread.observe(
                    float(np.linalg.norm(defender.position - centre[0])), clock
                )

            target_move = observer.displacement(nearest.player_id)
            defender_move = observer.displacement(defender.player_id)
            if target_move is None or defender_move is None:
                continue
            if float(np.linalg.norm(target_move)) < MIN_DISPLACEMENT:
                # The attacker stood still, so the defender's behaviour is uninformative.
                continue
            record.alignment.observe(
                cosine_similarity(defender_move, target_move), clock
            )

        for defender in defenders:
            verdict = self.defenders[defender.player_id].scheme(clock)
            if verdict is not None:
                self._verdicts.observe(verdict, clock, weight=1.0 / len(defenders))

    # -- read surface ----------------------------------------------------------

    def scheme(self, clock: float) -> Estimate[MarkingScheme]:
        """The team's marking scheme.

        ``MIXED`` is a positive finding, not a failure to decide: plenty of teams
        man-mark in some areas and zone in others, and reporting that is more useful
        than reporting nothing. Genuine lack of evidence shows up as immaturity instead.
        """
        weights = self._verdicts.weights_at(clock)
        total = float(sum(weights.values()))
        value: MarkingScheme | None = None
        if total > 0:
            man_share = weights.get(MarkingScheme.MAN, 0.0) / total
            if man_share >= SCHEME_MAJORITY:
                value = MarkingScheme.MAN
            elif (1.0 - man_share) >= SCHEME_MAJORITY:
                value = MarkingScheme.ZONAL
            else:
                value = MarkingScheme.MIXED
        return Estimate(
            value=value,
            observations=total,
            maturity_threshold=SCHEME_MATURITY,
            updated_at=clock,
            detail={
                "man_share": (
                    weights.get(MarkingScheme.MAN, 0.0) / total if total else 0.0
                )
            },
        )

    def assignments(self, clock: float) -> dict[int, Estimate[int]]:
        """Who each defender appears to be marking.

        Only defenders currently reading as man-markers get an entry: a zonal defender
        has a nearest attacker at every instant, but calling that an assignment would be
        inventing a relationship that is not there.
        """
        out: dict[int, Estimate[int]] = {}
        for defender_id, record in self.defenders.items():
            if record.scheme(clock) is not MarkingScheme.MAN:
                continue
            target = record.target(clock)
            if target is None:
                continue
            out[defender_id] = Estimate(
                value=target[0],
                observations=record.targets.total_at(clock),
                maturity_threshold=DEFENDER_MATURITY,
                updated_at=clock,
                detail={
                    "stability": target[1],
                    "alignment": record.alignment.mean,
                    "distance": record.distance.mean,
                },
            )
        return out

    def marker_of(self, attacker_id: int, clock: float) -> Estimate[int] | None:
        """Which defender is marking a given attacker, if any.

        The query the ranking layer actually wants: "who is on our target forward" feeds
        §5's ``mismatch_bonus`` directly.
        """
        best: Estimate[int] | None = None
        for defender_id, estimate in self.assignments(clock).items():
            if estimate.value != attacker_id:
                continue
            candidate = Estimate(
                value=defender_id,
                observations=estimate.observations,
                maturity_threshold=estimate.maturity_threshold,
                updated_at=estimate.updated_at,
                detail=estimate.detail,
            )
            if best is None or candidate.observations > best.observations:
                best = candidate
        return best

    def zones(self, clock: float) -> dict[int, tuple[np.ndarray, float]]:
        """Zone centre and radius per defender currently reading as zonal."""
        return {
            defender_id: record.zone(clock)
            for defender_id, record in self.defenders.items()
            if record.scheme(clock) is MarkingScheme.ZONAL and record.zone(clock)
        }
