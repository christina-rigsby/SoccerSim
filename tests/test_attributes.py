"""The attribute model and the two scales it has to reconcile.

The interesting cases are all about the seam between the 0–100 attribute scale and the
SI physical scale — particularly ``reaction_time``, where lower is better and a naive
normalisation silently inverts the meaning of every comparison.
"""

import pytest

from soccersim.domain.attributes import (
    ATTRIBUTE_MAX,
    PHYSICAL_RANGES,
    Attributes,
    Foot,
    normalised_physical,
)


class TestAttributes:
    def test_every_attribute_defaults_mid_scale(self):
        attributes = Attributes()
        assert all(attributes.get(name) == 50.0 for name in attributes.names()
                   if name != "weak_foot")

    def test_names_are_stable_and_complete(self):
        assert len(Attributes.names()) == 13
        assert "crossing" in Attributes.names()
        assert "max_speed" not in Attributes.names(), "physical lives in CapabilityProfile"

    def test_normalises_onto_the_unit_interval(self):
        assert Attributes(crossing=82).normalised("crossing") == pytest.approx(0.82)
        assert Attributes(crossing=0).normalised("crossing") == 0.0
        assert Attributes(crossing=100).normalised("crossing") == 1.0

    @pytest.mark.parametrize("value", [-1.0, 101.0, 1000.0])
    def test_rejects_out_of_scale_values(self, value):
        with pytest.raises(ValueError, match="outside the"):
            Attributes(finishing=value)

    def test_unknown_attribute_error_lists_the_known_ones(self):
        with pytest.raises(KeyError) as error:
            Attributes().get("pace")
        assert "crossing" in str(error.value)

    def test_is_immutable(self):
        with pytest.raises(Exception):
            Attributes().crossing = 90  # type: ignore[misc]

    def test_as_dict_round_trips(self):
        original = Attributes(crossing=71, finishing=64)
        assert Attributes(**original.as_dict()) == original


class TestPhysicalNormalisation:
    def test_range_endpoints_map_to_zero_and_one(self):
        low, high = PHYSICAL_RANGES["max_speed"]
        assert normalised_physical("max_speed", low) == 0.0
        assert normalised_physical("max_speed", high) == 1.0

    def test_clips_beyond_the_range(self):
        assert normalised_physical("max_speed", 99.0) == 1.0
        assert normalised_physical("max_speed", 0.0) == 0.0

    def test_monotone_in_value(self):
        values = [normalised_physical("max_speed", v) for v in (6.0, 7.0, 8.0, 9.0)]
        assert values == sorted(values)

    def test_reaction_time_inverts_so_lower_is_better(self):
        """The one attribute where a naive normalisation would reverse every ranking."""
        quick = normalised_physical("reaction_time", 0.16)
        slow = normalised_physical("reaction_time", 0.32)
        assert quick > slow

    def test_every_range_is_used_by_the_resolver(self):
        for name, (low, high) in PHYSICAL_RANGES.items():
            midpoint = (low + high) / 2
            assert 0.0 <= normalised_physical(name, midpoint) <= 1.0

    def test_unknown_physical_name_is_rejected(self):
        with pytest.raises(KeyError, match="unknown physical attribute"):
            normalised_physical("stamina", 1.0)


class TestFoot:
    def test_two_footed_flag(self):
        assert Foot.BOTH.is_two_footed
        assert not Foot.LEFT.is_two_footed
        assert not Foot.RIGHT.is_two_footed

    def test_values_match_the_roster_vocabulary(self):
        assert {f.value for f in Foot} == {"left", "right", "both"}


def test_attribute_scale_constant_matches_normalisation():
    """Guard against the scale constant and the divisor drifting apart."""
    assert Attributes(crossing=ATTRIBUTE_MAX).normalised("crossing") == 1.0
