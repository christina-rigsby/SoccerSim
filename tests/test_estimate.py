"""Confidence machinery.

The property that matters most is that an immature estimate cannot be acted on by
accident: ``mature_value`` must return ``None``, so the natural ``if ... is not None``
gets the safe behaviour without the caller having to remember anything.
"""

import pytest

from soccersim.dashboard.estimate import (
    DecayingMean,
    DecayingRate,
    DecayingTally,
    Estimate,
    cosine_similarity,
)


class TestEstimate:
    def test_immature_below_threshold(self):
        estimate = Estimate(value=0.8, observations=3.0, maturity_threshold=10.0)
        assert not estimate.is_mature
        assert estimate.mature_value is None
        assert estimate.value == 0.8, "the provisional guess stays inspectable"

    def test_mature_at_the_threshold(self):
        assert Estimate(value=1, observations=10.0, maturity_threshold=10.0).is_mature

    def test_a_none_value_is_never_mature(self):
        assert not Estimate(value=None, observations=99.0, maturity_threshold=1.0).is_mature

    def test_maturity_is_a_bounded_fraction(self):
        assert Estimate(None, 5.0, 10.0).maturity == pytest.approx(0.5)
        assert Estimate(1, 50.0, 10.0).maturity == 1.0

    def test_zero_threshold_is_always_mature(self):
        assert Estimate(value=1, observations=0.0, maturity_threshold=0.0).maturity == 1.0

    def test_require_mature_explains_the_shortfall(self):
        with pytest.raises(ValueError, match="3.0 of 10.0 observations"):
            Estimate(value=1, observations=3.0, maturity_threshold=10.0).require_mature()

    def test_require_mature_returns_the_value_when_ready(self):
        assert Estimate(value=7, observations=10.0, maturity_threshold=1.0).require_mature() == 7

    def test_describe_flags_immaturity(self):
        assert "immature" in Estimate(0.5, 1.0, 10.0).describe("x")
        assert "immature" not in Estimate(0.5, 20.0, 10.0).describe("x")


class TestDecayingMean:
    def test_mean_of_constant_observations(self):
        mean = DecayingMean(half_life=100.0)
        for t in range(5):
            mean.observe(4.0, float(t))
        assert mean.mean == pytest.approx(4.0)

    def test_recent_evidence_dominates(self):
        """A team that pressed early and sat deep later should not read as the average."""
        mean = DecayingMean(half_life=10.0)
        mean.observe(0.0, 0.0)
        mean.observe(1.0, 100.0)
        assert mean.mean > 0.99

    def test_weight_decays_with_idle_time(self):
        mean = DecayingMean(half_life=100.0)
        mean.observe(1.0, 0.0)
        assert mean.weight_at(100.0) == pytest.approx(0.5)
        assert mean.weight_at(200.0) == pytest.approx(0.25)

    def test_a_stale_estimate_stops_being_mature(self):
        """Evidence expiring is the point: an old read should not stay actionable."""
        mean = DecayingMean(half_life=10.0)
        for t in range(20):
            mean.observe(1.0, float(t))
        assert mean.estimate(20.0, threshold=5.0).is_mature
        assert not mean.estimate(200.0, threshold=5.0).is_mature

    def test_no_observations_means_no_value(self):
        assert DecayingMean().mean is None
        assert DecayingMean().estimate(0.0, 1.0).value is None

    def test_weights_scale_influence(self):
        mean = DecayingMean(half_life=1000.0)
        mean.observe(0.0, 0.0, weight=1.0)
        mean.observe(10.0, 0.0, weight=3.0)
        assert mean.mean == pytest.approx(7.5)

    @pytest.mark.parametrize("bad", [0.0, -1.0])
    def test_rejects_bad_half_life_and_weight(self, bad):
        with pytest.raises(ValueError):
            DecayingMean(half_life=bad)
        with pytest.raises(ValueError):
            DecayingMean().observe(1.0, 0.0, weight=bad)


class TestDecayingTally:
    def test_leader_and_share(self):
        tally = DecayingTally(half_life=1000.0)
        for _ in range(8):
            tally.observe("man", 0.0)
        for _ in range(2):
            tally.observe("zonal", 0.0)
        assert tally.leader(0.0) == ("man", pytest.approx(0.8))
        assert tally.share("zonal", 0.0) == pytest.approx(0.2)

    def test_share_of_an_unseen_key_is_zero(self):
        assert DecayingTally().share("nope", 0.0) == 0.0

    def test_empty_tally_has_no_leader(self):
        assert DecayingTally().leader(0.0) is None

    def test_min_share_suppresses_a_near_tie(self):
        """'Seen a lot and genuinely ambiguous' is not the same as 'not seen enough',
        and reporting a coin-flip as a finding would conflate them."""
        tally = DecayingTally(half_life=1000.0)
        for _ in range(50):
            tally.observe("a", 0.0)
        for _ in range(49):
            tally.observe("b", 0.0)
        assert tally.estimate(0.0, threshold=5.0, min_share=0.6).value is None
        assert tally.estimate(0.0, threshold=5.0, min_share=0.4).value == "a"

    def test_estimate_carries_shares_in_detail(self):
        tally = DecayingTally(half_life=1000.0)
        tally.observe("a", 0.0)
        assert tally.estimate(0.0, 1.0).detail["shares"]["a"] == pytest.approx(1.0)

    def test_totals_decay(self):
        tally = DecayingTally(half_life=10.0)
        tally.observe("a", 0.0)
        assert tally.total_at(10.0) == pytest.approx(0.5)


class TestDecayingRate:
    def test_rate_is_hits_over_trials(self):
        rate = DecayingRate(half_life=1000.0)
        for hit in (True, True, True, False):
            rate.observe("k", hit, 0.0)
        assert rate.rate("k", 0.0) == pytest.approx(0.75)

    def test_misses_count_as_evidence(self):
        """The whole point: counting only hits would measure how often the *condition*
        occurs, not how often it leads anywhere."""
        rate = DecayingRate(half_life=1000.0)
        for _ in range(3):
            rate.observe("common", True, 0.0)
        for _ in range(97):
            rate.observe("common", False, 0.0)
        assert rate.rate("common", 0.0) == pytest.approx(0.03)

    def test_unseen_key_has_no_rate(self):
        assert DecayingRate().rate("k", 0.0) is None

    def test_above_requires_both_rate_and_evidence(self):
        rate = DecayingRate(half_life=1000.0)
        rate.observe("thin", True, 0.0)  # 100% on one trial
        for hit in (True, True, True, True, False):
            rate.observe("solid", hit, 0.0)
        assert rate.above(0.0, min_rate=0.5, threshold=4.0) == {"solid": pytest.approx(0.8)}

    def test_estimate_reports_trials_as_observations(self):
        rate = DecayingRate(half_life=1000.0)
        for hit in (True, False):
            rate.observe("k", hit, 0.0)
        estimate = rate.estimate("k", 0.0, threshold=2.0)
        assert estimate.observations == pytest.approx(2.0)
        assert estimate.is_mature


class TestCosineSimilarity:
    def test_parallel_and_opposed(self):
        assert cosine_similarity([1, 0], [2, 0]) == pytest.approx(1.0)
        assert cosine_similarity([1, 0], [-1, 0]) == pytest.approx(-1.0)

    def test_orthogonal(self):
        assert cosine_similarity([1, 0], [0, 1]) == pytest.approx(0.0)

    def test_degenerate_vectors_are_neutral_not_nan(self):
        """A player who did not move told us nothing, so the frame must neither support
        nor contradict the hypothesis."""
        assert cosine_similarity([0, 0], [1, 0]) == 0.0
        assert cosine_similarity([0, 0], [0, 0]) == 0.0
