"""Player attributes — the technical and mental ratings role matching reads.

Two deliberately separate namespaces, because they are measured in different things:

**Technical / mental attributes** live here, on a 0–100 integer scale. That scale is a
convention borrowed from football management games; it has no physical meaning and is
only ever compared against other attributes on the same scale. Internally everything
normalises to 0–1 before it is combined.

**Physical capability** stays in :class:`~soccersim.domain.entities.CapabilityProfile`,
in SI units (m/s, m/s², s), because :mod:`soccersim.kinematics` does real physics with
it. Converting a 0–100 "pace" rating into metres per second would mean inventing a
mapping and then doing physics with a made-up number.

Role matching needs to read both, so :func:`normalised_physical` projects the SI values
onto the same 0–1 scale using the reference ranges below. Those ranges are calibration
guesses (see Q-020), not fitted values.

Every attribute here is read by at least one role in
:mod:`soccersim.domain.roles`. An attribute with no consumer is a number that invites
false precision and drifts out of date, so the set stays lean on purpose.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum

import numpy as np

#: Attributes are authored and stored on this scale.
ATTRIBUTE_MIN = 0.0
ATTRIBUTE_MAX = 100.0


class Foot(Enum):
    """Preferred foot."""

    LEFT = "left"
    RIGHT = "right"
    BOTH = "both"

    @property
    def is_two_footed(self) -> bool:
        return self is Foot.BOTH


@dataclass(frozen=True)
class Attributes:
    """A player's technical and mental ratings, each 0–100.

    Grouped by phase of play. The docstring for each names the role or action from the
    design doc that reads it, so it is always clear why an attribute exists.
    """

    # -- on the ball ----------------------------------------------------------
    passing_short: float = 50.0
    """Possession buildup through midfield; the outlet pass in a 3-pass counter."""

    passing_long: float = 50.0
    """Direct/long-ball to a target forward; the switch in switch-and-cross."""

    crossing: float = 50.0
    """Every wing-overload play ends in a cross or cutback."""

    finishing: float = 50.0
    """`shoot(target)` — any role that ends a move."""

    dribbling: float = 50.0
    """`dribble(waypoint)`; the winger cutting inside on an overlap."""

    first_touch: float = 50.0
    """`first_touch(direction)`; receiving under pressure as a target forward."""

    # -- duels ----------------------------------------------------------------
    heading: float = 50.0
    """`header(target)` — the box target on a cross, and set pieces."""

    strength: float = 50.0
    """`shield(pressure_source)`; holding the ball up as a target forward."""

    # -- off the ball, defensive ----------------------------------------------
    tackling: float = 50.0
    """`tackle(opponent_id)`, `press(target)`."""

    marking: float = 50.0
    """`mark_man(opponent_id)`, `mark_zone(zone_id)`, set-piece assignments."""

    positioning: float = 50.0
    """`intercept_lane`, `track_run`, holding defensive shape, `step_up` timing."""

    work_rate: float = 50.0
    """High press and trap press; repeated overlap runs across a match."""

    # -- footedness -----------------------------------------------------------
    weak_foot: float = 40.0
    """Quality on the non-preferred foot.

    Matters more than it looks: an inverted winger on the right wing is a left-footed
    player, and a cutback is struck with whichever foot the run leaves available.
    """

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if not ATTRIBUTE_MIN <= float(value) <= ATTRIBUTE_MAX:
                raise ValueError(
                    f"attribute {name!r} is {value}, outside the "
                    f"{ATTRIBUTE_MIN:.0f}–{ATTRIBUTE_MAX:.0f} scale"
                )

    # -- access ---------------------------------------------------------------

    @classmethod
    def names(cls) -> tuple[str, ...]:
        """Every attribute name, in declaration order."""
        return tuple(cls.__dataclass_fields__)

    def get(self, name: str) -> float:
        """Raw 0–100 value, raising a helpful error for an unknown name."""
        try:
            return float(getattr(self, name))
        except AttributeError:
            raise KeyError(
                f"unknown attribute {name!r}; known attributes are "
                f"{', '.join(self.names())}"
            ) from None

    def normalised(self, name: str) -> float:
        """Value of ``name`` projected onto 0–1."""
        return self.get(name) / ATTRIBUTE_MAX

    def as_dict(self) -> dict[str, float]:
        return {name: float(getattr(self, name)) for name in self.names()}


#: Plausible outfield ranges for the SI physical values, used only to put them on the
#: same 0–1 scale as the 0–100 attributes. Calibration guesses (Q-020): the floor is a
#: slow goalkeeper and the ceiling an elite sprinter, so a typical outfielder lands
#: mid-scale rather than at either end.
PHYSICAL_RANGES: dict[str, tuple[float, float]] = {
    "max_speed": (5.5, 9.2),  # m/s
    "max_accel": (4.5, 8.0),  # m/s^2
    "reaction_time": (0.34, 0.14),  # s — inverted: lower is better
}

#: Names that resolve against the physical profile rather than the attribute set.
PHYSICAL_NAMES = frozenset(PHYSICAL_RANGES)


def normalised_physical(name: str, value: float) -> float:
    """Project an SI physical value onto 0–1, clipped.

    Ranges may be inverted (``reaction_time``, where lower is better); the arithmetic
    handles that without a special case, so "higher is always better" holds for every
    normalised value the matcher sees.
    """
    try:
        low, high = PHYSICAL_RANGES[name]
    except KeyError:
        raise KeyError(
            f"unknown physical attribute {name!r}; known are "
            f"{', '.join(sorted(PHYSICAL_RANGES))}"
        ) from None
    return float(np.clip((value - low) / (high - low), 0.0, 1.0))
