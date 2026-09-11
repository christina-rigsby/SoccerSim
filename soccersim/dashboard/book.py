"""Our own play-usage history — the feedback loop §5 calls the "book".

Two of §5's soft constraints read our own history rather than the opponent's, and so need
no inference at all:

``predictability_penalty`` — "decaying penalty proportional to recent-usage count of a
given play against similar opponent situations — encourages diversification over a
match". Recorded here, keyed by play and situation, with decay so a play used early stops
being penalised later.

``historical_success_rate`` — "penalise/reward based on this play's empirical success
rate for this team... should dominate over time as data accumulates". Recorded as a
conditional rate, which is why outcomes are logged separately from usage.

No plays exist yet (M1), so play keys are opaque strings. That is deliberate: the book
does not need to know what a play *is* to count it, and wiring it up later is a matter of
passing real keys.

One thing this cannot yet decide: Q-013 asks whether a play aborted mid-execution counts
as a failure. :meth:`record_outcome` takes an explicit outcome so the answer can be
supplied by the caller rather than assumed here.
"""

from __future__ import annotations

from dataclasses import dataclass

from .estimate import DEFAULT_HALF_LIFE, DecayingRate, DecayingTally, Estimate

#: Usage decays faster than opponent-model evidence: §5 wants diversification *within* a
#: match, so a play used ten minutes ago should have largely stopped being penalised.
USAGE_HALF_LIFE = 300.0

#: Outcomes decay far more slowly — success rate is meant to "dominate over time as data
#: accumulates", which it cannot do if the evidence keeps evaporating.
OUTCOME_HALF_LIFE = 3600.0

#: Effective attempts before a success rate is actionable.
SUCCESS_MATURITY = 5.0


@dataclass(frozen=True)
class PlayUsage:
    play_key: str
    situation: tuple[str, ...]
    recent_count: float
    last_used: float | None


class PlayBook:
    """Usage and outcome history for our own plays."""

    def __init__(
        self,
        usage_half_life: float = USAGE_HALF_LIFE,
        outcome_half_life: float = OUTCOME_HALF_LIFE,
    ) -> None:
        self._usage = DecayingTally(usage_half_life)
        self._by_play = DecayingTally(usage_half_life)
        self._outcomes = DecayingRate(outcome_half_life)
        self._last_used: dict[str, float] = {}
        self.total_recorded = 0

    # -- recording -------------------------------------------------------------

    def record_use(
        self, play_key: str, situation: tuple[str, ...], clock: float
    ) -> None:
        """Note that we ran ``play_key`` in ``situation``."""
        self._usage.observe((play_key, situation), clock)
        self._by_play.observe(play_key, clock)
        self._last_used[play_key] = clock
        self.total_recorded += 1

    def record_outcome(self, play_key: str, succeeded: bool, clock: float) -> None:
        """Note how a play turned out.

        ``succeeded`` is the caller's judgement, not this module's. Whether an aborted
        play counts as a failure is genuinely unresolved (Q-013) — crediting the abort to
        the play would teach the system to avoid plays it correctly abandoned — so the
        decision stays with whoever has the context to make it.
        """
        self._outcomes.observe(play_key, succeeded, clock)

    # -- read surface ----------------------------------------------------------

    def recent_usage(
        self, play_key: str, situation: tuple[str, ...], clock: float
    ) -> float:
        """Decayed count of this play in this situation."""
        return self._usage.weights_at(clock).get((play_key, situation), 0.0)

    def total_usage(self, play_key: str, clock: float) -> float:
        """Decayed count of this play in any situation."""
        return self._by_play.weights_at(clock).get(play_key, 0.0)

    def predictability(
        self, play_key: str, situation: tuple[str, ...], clock: float
    ) -> float:
        """Usage share of this play within this situation, in ``[0, 1]``.

        A share rather than a raw count, so the penalty means "how much of our recent
        behaviour here has been this play" — which is what an opponent could actually
        pick up on. A raw count would also penalise a play simply because the situation
        recurred often.
        """
        weights = self._usage.weights_at(clock)
        in_situation = {
            key: weight for key, weight in weights.items() if key[1] == situation
        }
        total = sum(in_situation.values())
        if total <= 0:
            return 0.0
        return in_situation.get((play_key, situation), 0.0) / total

    def success_rate(self, play_key: str, clock: float) -> Estimate[float]:
        """Empirical success rate for this play."""
        return self._outcomes.estimate(play_key, clock, SUCCESS_MATURITY)

    def last_used(self, play_key: str) -> float | None:
        return self._last_used.get(play_key)

    def most_used(self, clock: float, limit: int = 5) -> list[PlayUsage]:
        weights = self._usage.weights_at(clock)
        ranked = sorted(weights.items(), key=lambda item: item[1], reverse=True)
        return [
            PlayUsage(
                play_key=str(key[0]),
                situation=tuple(key[1]),
                recent_count=weight,
                last_used=self._last_used.get(str(key[0])),
            )
            for key, weight in ranked[:limit]
        ]

    def describe(self, clock: float) -> str:
        if not self.total_recorded:
            return "book: no plays recorded"
        lines = [f"book: {self.total_recorded} uses recorded"]
        for usage in self.most_used(clock):
            rate = self.success_rate(usage.play_key, clock)
            lines.append(
                f"  {usage.play_key:<22} {'/'.join(usage.situation):<28} "
                f"recent {usage.recent_count:.2f}  "
                f"predictability {self.predictability(usage.play_key, usage.situation, clock):.0%}  "
                f"{rate.describe('success')}"
            )
        return "\n".join(lines)
