"""Estimates that carry how much they can be trusted.

Every quantity the dashboard infers is wrapped in an :class:`Estimate`, which records
how many (decayed) observations back it and whether that clears the estimator's maturity
threshold.

This exists because of a specific failure mode. §5's ``mismatch_bonus`` feeds
opponent-model data straight into play ranking: "reward for plays targeting a specific
weak defender identified in the opponent model". If the model is confidently wrong after
one possession, plays get selected on noise — and because the resulting play then
generates more observations of its own choosing, the error is self-reinforcing. A point
estimate with no notion of maturity makes that mistake impossible to guard against
(D-023).

The API is shaped so the safe thing is also the obvious thing: :attr:`Estimate.value`
always returns the current best guess for inspection, but :attr:`Estimate.mature_value`
returns ``None`` until the threshold is crossed, so a consumer writing the natural
``if estimate.mature_value is not None`` gets the correct behaviour by default.

Observations are **decayed**, not counted: a team that pressed in the first half and sits
deep in the second should not be described by an average of the two. Decay is by
half-life in seconds of match time, so ``observations`` is an *effective* count and is
fractional.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, Hashable, TypeVar

import numpy as np

T = TypeVar("T")

#: Evidence older than this loses half its weight. Chosen so a tactical change at
#: half-time is reflected within a few minutes rather than averaged away. Uncalibrated
#: (Q-025).
DEFAULT_HALF_LIFE = 180.0


@dataclass(frozen=True)
class Estimate(Generic[T]):
    """An inferred value plus the evidence behind it."""

    value: T | None
    #: Effective observation count after decay — fractional, and it *falls* when no new
    #: evidence arrives, so a stale estimate eventually stops being mature.
    observations: float
    maturity_threshold: float
    #: Match clock of the most recent supporting observation.
    updated_at: float = 0.0
    #: Free-form supporting detail (per-category weights, per-player breakdowns).
    detail: dict = field(default_factory=dict)

    @property
    def is_mature(self) -> bool:
        """Whether there is enough evidence to act on this."""
        return self.value is not None and self.observations >= self.maturity_threshold

    @property
    def maturity(self) -> float:
        """Progress toward the threshold, in ``[0, 1]``."""
        if self.maturity_threshold <= 0:
            return 1.0
        return float(min(1.0, self.observations / self.maturity_threshold))

    @property
    def mature_value(self) -> T | None:
        """The value if it can be trusted, else ``None``.

        Prefer this over :attr:`value` everywhere a decision is made. ``value`` is for
        looking at; ``mature_value`` is for acting on.
        """
        return self.value if self.is_mature else None

    def require_mature(self, what: str = "estimate") -> T:
        """The value, or an error explaining how much evidence is still needed."""
        if not self.is_mature:
            raise ValueError(
                f"{what} is not mature: {self.observations:.1f} of "
                f"{self.maturity_threshold:.1f} observations "
                f"({self.maturity:.0%}). Use .value to inspect the provisional guess, "
                "or .mature_value to branch on availability."
            )
        return self.value  # type: ignore[return-value]

    def describe(self, name: str = "") -> str:
        label = f"{name}: " if name else ""
        if self.value is None:
            return f"{label}no estimate ({self.observations:.1f} obs)"
        mark = "" if self.is_mature else f"  [immature {self.maturity:.0%}]"
        shown = f"{self.value:.3f}" if isinstance(self.value, float) else str(self.value)
        return f"{label}{shown}  ({self.observations:.1f} obs){mark}"


class DecayingMean:
    """A running mean with exponential time decay.

    ``observe`` may be called at irregular intervals; decay is applied by elapsed match
    time rather than by update count, so an estimator that runs at 10 Hz and one that
    runs once per possession age at the same rate.
    """

    def __init__(self, half_life: float = DEFAULT_HALF_LIFE) -> None:
        if half_life <= 0:
            raise ValueError("half_life must be positive")
        self.half_life = float(half_life)
        self._total = 0.0
        self._weight = 0.0
        self._last_t: float | None = None

    def _decay_to(self, clock: float) -> None:
        if self._last_t is None:
            self._last_t = clock
            return
        elapsed = clock - self._last_t
        if elapsed <= 0:
            return
        factor = 0.5 ** (elapsed / self.half_life)
        self._total *= factor
        self._weight *= factor
        self._last_t = clock

    def observe(self, value: float, clock: float, weight: float = 1.0) -> None:
        if weight <= 0:
            raise ValueError("weight must be positive")
        self._decay_to(clock)
        self._total += float(value) * weight
        self._weight += weight

    def weight_at(self, clock: float) -> float:
        """Effective observation count as of ``clock``, after decay."""
        if self._last_t is None:
            return 0.0
        elapsed = max(0.0, clock - self._last_t)
        return self._weight * 0.5 ** (elapsed / self.half_life)

    @property
    def mean(self) -> float | None:
        if self._weight <= 0:
            return None
        return self._total / self._weight

    def estimate(self, clock: float, threshold: float) -> Estimate[float]:
        return Estimate(
            value=self.mean,
            observations=self.weight_at(clock),
            maturity_threshold=threshold,
            updated_at=self._last_t or 0.0,
        )


class DecayingTally:
    """Decayed weights over categorical outcomes — a vote that forgets.

    Used wherever the question is "which of these, and how sure" rather than "how much":
    man-marking versus zonal, and which pass types provoke a press.
    """

    def __init__(self, half_life: float = DEFAULT_HALF_LIFE) -> None:
        if half_life <= 0:
            raise ValueError("half_life must be positive")
        self.half_life = float(half_life)
        self._weights: dict[Hashable, float] = {}
        self._last_t: float | None = None

    def _decay_to(self, clock: float) -> None:
        if self._last_t is None:
            self._last_t = clock
            return
        elapsed = clock - self._last_t
        if elapsed <= 0:
            return
        factor = 0.5 ** (elapsed / self.half_life)
        self._weights = {key: w * factor for key, w in self._weights.items()}
        self._last_t = clock

    def observe(self, key: Hashable, clock: float, weight: float = 1.0) -> None:
        if weight <= 0:
            raise ValueError("weight must be positive")
        self._decay_to(clock)
        self._weights[key] = self._weights.get(key, 0.0) + weight

    def weights_at(self, clock: float) -> dict[Hashable, float]:
        if self._last_t is None:
            return {}
        factor = 0.5 ** (max(0.0, clock - self._last_t) / self.half_life)
        return {key: w * factor for key, w in self._weights.items()}

    def total_at(self, clock: float) -> float:
        return float(sum(self.weights_at(clock).values()))

    def share(self, key: Hashable, clock: float) -> float:
        """``key``'s share of the total weight, or 0 when there is no evidence."""
        weights = self.weights_at(clock)
        total = sum(weights.values())
        if total <= 0:
            return 0.0
        return weights.get(key, 0.0) / total

    def leader(self, clock: float) -> tuple[Hashable, float] | None:
        """The heaviest key and its share."""
        weights = self.weights_at(clock)
        if not weights:
            return None
        key = max(weights, key=weights.get)
        total = sum(weights.values())
        return key, weights[key] / total

    def estimate(
        self, clock: float, threshold: float, min_share: float = 0.0
    ) -> Estimate:
        """Leading category as an estimate.

        ``min_share`` guards against declaring a winner from a near-tie: below it the
        value is ``None`` however many observations there are, because "we have seen a
        lot and it is genuinely ambiguous" is a different state from "we have not seen
        enough", and conflating them would report a coin-flip as a finding.
        """
        weights = self.weights_at(clock)
        total = float(sum(weights.values()))
        leader = self.leader(clock)
        value = None
        if leader is not None and leader[1] >= min_share:
            value = leader[0]
        return Estimate(
            value=value,
            observations=total,
            maturity_threshold=threshold,
            updated_at=self._last_t or 0.0,
            detail={"weights": dict(weights), "shares": {
                key: (w / total if total else 0.0) for key, w in weights.items()
            }},
        )


class DecayingRate:
    """A decayed success rate — how often a condition holds, not how often it is seen.

    The distinction matters for press triggers. Counting presses that followed backpasses
    tells you mostly that backpasses are common. What you want is ``P(press | backpass)``,
    which needs the unpressed backpasses counted too.
    """

    def __init__(self, half_life: float = DEFAULT_HALF_LIFE) -> None:
        self._hits = DecayingTally(half_life)
        self._trials = DecayingTally(half_life)
        self.half_life = float(half_life)

    def observe(self, key: Hashable, hit: bool, clock: float, weight: float = 1.0) -> None:
        self._trials.observe(key, clock, weight)
        if hit:
            self._hits.observe(key, clock, weight)

    def trials(self, key: Hashable, clock: float) -> float:
        return self.weights_at(clock).get(key, (0.0, 0.0))[0]

    def weights_at(self, clock: float) -> dict[Hashable, tuple[float, float]]:
        trials = self._trials.weights_at(clock)
        hits = self._hits.weights_at(clock)
        return {key: (t, hits.get(key, 0.0)) for key, t in trials.items()}

    def rate(self, key: Hashable, clock: float) -> float | None:
        entry = self.weights_at(clock).get(key)
        if entry is None or entry[0] <= 0:
            return None
        return entry[1] / entry[0]

    def estimate(self, key: Hashable, clock: float, threshold: float) -> Estimate[float]:
        entry = self.weights_at(clock).get(key, (0.0, 0.0))
        trials, hits = entry
        return Estimate(
            value=(hits / trials) if trials > 0 else None,
            observations=trials,
            maturity_threshold=threshold,
            updated_at=self._trials._last_t or 0.0,
            detail={"trials": trials, "hits": hits},
        )

    def above(self, clock: float, min_rate: float, threshold: float) -> dict[Hashable, float]:
        """Keys whose rate exceeds ``min_rate`` on enough evidence to be mature."""
        out = {}
        for key, (trials, hits) in self.weights_at(clock).items():
            if trials >= threshold and trials > 0 and hits / trials >= min_rate:
                out[key] = hits / trials
        return out


def cosine_similarity(a, b) -> float:
    """Cosine similarity of two vectors, 0 when either is degenerate.

    Used to ask whether a defender moved *with* an attacker. Returning 0 rather than NaN
    for a stationary frame means such frames neither support nor contradict the
    hypothesis, which is the right treatment: a defender who did not move told us
    nothing.
    """
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    if na < 1e-9 or nb < 1e-9:
        return 0.0
    return float(np.clip(a @ b / (na * nb), -1.0, 1.0))
