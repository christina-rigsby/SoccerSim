"""Pressing inference — what provokes a press, and how hard it is.

§2 asks for "pressing triggers: what provokes a press, press intensity, press trap
tendencies". §3 names the likely trigger: "initiated on backpass or sideways pass near
opponent box".

The measurement is easy — :func:`~soccersim.dashboard.measurements.pressure_on_ball`
gives per-frame intensity. The inference is where the care goes, and it turns on one
thing: **a trigger is a conditional rate, not a count.**

Counting the presses that followed a backpass mostly tells you that backpasses are
common. What matters is ``P(press | backpass in the middle third)``, which requires
counting the backpasses that were *not* pressed too. So every pass is entered as a trial
and labelled a hit or a miss once its lookahead window has elapsed — deferred labelling
via a pending queue, because at the moment a pass happens you cannot yet know whether a
press followed (D-025).

Without that, any team that passes backwards a lot would be diagnosed as pressing on
backpasses, and §5's ``mismatch_bonus`` would act on an artefact of pass frequency.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from ..domain.entities import Team
from ..domain.state import GameState
from .estimate import DEFAULT_HALF_LIFE, DecayingMean, DecayingRate, Estimate
from .measurements import pressure_on_ball
from .observer import EventKind, MatchObserver

#: Pressure intensity at which a press is considered underway.
PRESS_ONSET = 0.75

#: Seconds after a pass within which a press onset counts as triggered by it. Long
#: enough for a press to develop, short enough that an unrelated press later in the
#: possession is not miscredited.
TRIGGER_LOOKAHEAD = 2.5

#: Minimum conditional rate before a (direction, third) pair is reported as a trigger.
MIN_TRIGGER_RATE = 0.55

#: Effective trials before a trigger rate is actionable, and frames before the intensity
#: and frequency estimates are.
TRIGGER_MATURITY = 4.0
INTENSITY_MATURITY = 30.0


@dataclass
class _PendingPass:
    """A pass awaiting its verdict once the lookahead window closes."""

    key: tuple[str, str]
    clock: float
    pressed: bool = False


class PressingModel:
    """Infers ``subject``'s pressing behaviour against the other team's possession."""

    def __init__(self, subject: Team, half_life: float = DEFAULT_HALF_LIFE) -> None:
        self.subject = subject
        self.half_life = float(half_life)
        self.trigger_rates = DecayingRate(half_life)
        self.episode_intensity = DecayingMean(half_life)
        self.press_frequency = DecayingMean(half_life)
        self._pending: deque[_PendingPass] = deque()
        self._pressing_now = False
        self.onsets = 0

    def observe(self, state: GameState, observer: MatchObserver) -> None:
        """Take one frame of evidence.

        Frames where ``subject`` has the ball are skipped: a team cannot press while in
        possession, and counting those frames as "not pressing" would dilute the
        frequency estimate with time when pressing was not an option.
        """
        clock = float(state.clock_seconds)
        carrier = state.ball.carrier_id
        if carrier is None or state.team_of(carrier) is self.subject:
            self._resolve_pending(clock)
            return

        pressure = pressure_on_ball(state)
        intensity = pressure.intensity if pressure else 0.0
        pressing = intensity >= PRESS_ONSET

        self.press_frequency.observe(1.0 if pressing else 0.0, clock)
        if pressing:
            self.episode_intensity.observe(intensity, clock)

        if pressing and not self._pressing_now:
            self.onsets += 1
            # Credit every pass still inside its lookahead window.
            for pending in self._pending:
                if clock - pending.clock <= TRIGGER_LOOKAHEAD:
                    pending.pressed = True
        self._pressing_now = pressing

        # New passes by the team in possession become trials.
        for event in observer.recent_events((EventKind.PASS,), since=clock):
            if event.team is self.subject:
                continue
            key = (event.detail.get("direction", "unknown"), event.detail.get("third", "unknown"))
            self._pending.append(_PendingPass(key=key, clock=event.clock))

        self._resolve_pending(clock)

    def _resolve_pending(self, clock: float) -> None:
        while self._pending and clock - self._pending[0].clock >= TRIGGER_LOOKAHEAD:
            pending = self._pending.popleft()
            self.trigger_rates.observe(pending.key, pending.pressed, pending.clock)

    def flush(self, clock: float) -> None:
        """Resolve every pending pass, for end-of-scenario reporting.

        Passes still inside their window are counted as unpressed, which is the correct
        reading: the window expired without a press.
        """
        while self._pending:
            pending = self._pending.popleft()
            self.trigger_rates.observe(pending.key, pending.pressed, pending.clock)

    # -- read surface ----------------------------------------------------------

    def triggers(self, clock: float) -> dict[tuple[str, str], float]:
        """(direction, third) pairs that provoke a press often enough to count."""
        return {
            key: rate
            for key, rate in self.trigger_rates.above(
                clock, MIN_TRIGGER_RATE, TRIGGER_MATURITY
            ).items()
        }

    def trigger_estimate(
        self, direction: str, third: str, clock: float
    ) -> Estimate[float]:
        """``P(press | pass of this direction in this third)``."""
        return self.trigger_rates.estimate((direction, third), clock, TRIGGER_MATURITY)

    def intensity(self, clock: float) -> Estimate[float]:
        """Mean intensity *while pressing* — how hard they press when they do.

        Deliberately not averaged over all frames: a team that presses ferociously but
        rarely and one that harries constantly and mildly are tactically different, and
        a single diluted mean would report them identically. :meth:`frequency` carries
        the other half.
        """
        return self.episode_intensity.estimate(clock, INTENSITY_MATURITY)

    def frequency(self, clock: float) -> Estimate[float]:
        """Share of opposition-possession frames spent pressing."""
        return self.press_frequency.estimate(clock, INTENSITY_MATURITY)

    def describe(self, clock: float) -> str:
        triggers = self.triggers(clock)
        shown = (
            ", ".join(f"{d}/{t} {r:.0%}" for (d, t), r in sorted(triggers.items()))
            or "none identified"
        )
        return (
            f"press {self.intensity(clock).describe('intensity')}  "
            f"{self.frequency(clock).describe('frequency')}  "
            f"onsets={self.onsets}  triggers: {shown}"
        )
