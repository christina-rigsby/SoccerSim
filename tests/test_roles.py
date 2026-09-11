"""Play roles, fit scoring, and the catalogue.

Two properties matter most. First, fit must be *ordinal and explainable* — the absolute
number means nothing (D-022), so the tests assert orderings and contributions rather
than magnitudes. Second, minimums must gate correctly in both scales, including the
inverted one, since that is what §5's hard ``min_role_coverage`` rests on.
"""

import pytest

from soccersim.domain.attributes import Attributes, Foot
from soccersim.domain.entities import (
    CapabilityProfile,
    PlayerState,
    PositionalRole,
    Team,
)
from soccersim.domain.pitch import vec
from soccersim.domain.roles import (
    ARCHETYPE_CAPABILITY,
    ROLE_CATALOGUE,
    PlayRole,
    archetype_capability,
    get_role,
    rank_players,
    resolve_input,
    role_fit,
)


def player(
    player_id=1,
    slot=PositionalRole.RW,
    stamina=1.0,
    speed=8.0,
    available=True,
    **attributes,
):
    return PlayerState(
        player_id=player_id,
        team=Team.HOME,
        position=vec(0, 0),
        positional_role=slot,
        capability=CapabilityProfile(max_speed=speed, max_accel=6.5, reaction_time=0.2),
        stamina=stamina,
        available=available,
        attributes=Attributes(**attributes),
        foot=Foot.RIGHT,
    )


CROSSER = PlayRole(
    key="crosser", label="Crosser", description="", weights={"crossing": 1.0}
)


class TestPlayRoleValidation:
    def test_rejects_unknown_attribute_in_weights(self):
        with pytest.raises(ValueError, match="unknown attribute 'pace'"):
            PlayRole("x", "X", "", {"pace": 1.0})

    def test_rejects_unknown_attribute_in_minimums(self):
        with pytest.raises(ValueError, match="unknown attribute"):
            PlayRole("x", "X", "", {"crossing": 1.0}, minimums={"agility": 50.0})

    def test_rejects_empty_weights(self):
        with pytest.raises(ValueError, match="no weights"):
            PlayRole("x", "X", "", {})

    def test_rejects_non_positive_weight(self):
        with pytest.raises(ValueError, match="must be positive"):
            PlayRole("x", "X", "", {"crossing": 0.0})

    def test_rejects_physical_minimum_above_the_reference_range(self):
        """A minimum beyond the range would clip to 1.0 and pass every player."""
        with pytest.raises(ValueError, match="would pass every player"):
            PlayRole("x", "X", "", {"max_speed": 1.0}, minimums={"max_speed": 50.0})

    def test_rejects_attribute_minimum_off_scale(self):
        with pytest.raises(ValueError, match="outside the 0–100"):
            PlayRole("x", "X", "", {"crossing": 1.0}, minimums={"crossing": 150.0})

    def test_weights_normalise_to_one(self):
        role = PlayRole("x", "X", "", {"crossing": 3.0, "finishing": 1.0})
        assert sum(role.normalised_weights.values()) == pytest.approx(1.0)
        assert role.normalised_weights["crossing"] == pytest.approx(0.75)

    def test_inputs_lists_weighted_and_gated_names_once(self):
        role = PlayRole(
            "x", "X", "", {"crossing": 1.0}, minimums={"crossing": 40.0, "work_rate": 50.0}
        )
        assert set(role.inputs) == {"crossing", "work_rate"}
        assert len(role.inputs) == 2


class TestRoleFit:
    def test_score_tracks_the_weighted_attribute(self):
        assert role_fit(player(crossing=90), CROSSER).score == pytest.approx(0.90)

    def test_score_is_bounded(self):
        assert role_fit(player(crossing=0), CROSSER).score == pytest.approx(0.0)
        assert role_fit(player(crossing=100), CROSSER).score == pytest.approx(1.0)

    def test_contributions_sum_to_the_score(self):
        fit = role_fit(player(crossing=70, work_rate=60), get_role("overlap_runner"))
        assert sum(fit.contributions.values()) == pytest.approx(fit.score)

    def test_fit_is_ordinal_across_players(self):
        better = role_fit(player(crossing=80), CROSSER)
        worse = role_fit(player(crossing=40), CROSSER)
        assert better.score > worse.score

    def test_physical_inputs_use_fatigue_degraded_capability(self):
        """D-006 extended into role matching: a tired player is worse at a pace role."""
        role = PlayRole("pacey", "Pacey", "", {"max_speed": 1.0})
        fresh = role_fit(player(stamina=1.0, speed=8.5), role)
        tired = role_fit(player(stamina=0.0, speed=8.5), role)
        assert tired.score < fresh.score

    def test_technical_attributes_are_not_degraded_by_fatigue(self):
        """Fatigue is modelled as a physical effect only — a simplification (Q-021)."""
        fresh = role_fit(player(stamina=1.0, crossing=80), CROSSER)
        tired = role_fit(player(stamina=0.0, crossing=80), CROSSER)
        assert tired.score == pytest.approx(fresh.score)

    def test_missing_attributes_raise_an_explanatory_error(self):
        bare = PlayerState(1, Team.HOME, vec(0, 0))
        with pytest.raises(ValueError, match="inferred from observed play"):
            role_fit(bare, CROSSER)

    def test_practised_flag_is_recorded(self):
        unpractised = player()
        practised = PlayerState(
            1, Team.HOME, vec(0, 0), attributes=Attributes(),
            practised_roles=frozenset({"crosser"}),
        )
        assert not role_fit(unpractised, CROSSER).practised
        assert role_fit(practised, CROSSER).practised

    def test_limiting_factor_names_the_weakest_contribution(self):
        role = PlayRole("x", "X", "", {"crossing": 1.0, "finishing": 1.0})
        fit = role_fit(player(crossing=90, finishing=20), role)
        assert fit.limiting_factor == "finishing"

    def test_explain_mentions_a_failed_minimum(self):
        role = PlayRole("x", "X", "", {"crossing": 1.0}, minimums={"crossing": 80.0})
        assert "BELOW MINIMUM" in role_fit(player(crossing=40), role).explain()


class TestMinimums:
    def test_meeting_the_minimum_exactly_passes(self):
        role = PlayRole("x", "X", "", {"crossing": 1.0}, minimums={"crossing": 60.0})
        assert role_fit(player(crossing=60), role).meets_minimums

    def test_below_the_minimum_fails_and_reports_the_gap(self):
        role = PlayRole("x", "X", "", {"crossing": 1.0}, minimums={"crossing": 60.0})
        fit = role_fit(player(crossing=55), role)
        assert not fit.meets_minimums
        assert fit.unmet["crossing"] == (55.0, 60.0)

    def test_physical_minimums_gate_in_si_units(self):
        role = get_role("runner_in_behind")
        assert role_fit(player(speed=8.2), role).meets_minimums
        assert not role_fit(player(speed=7.9), role).meets_minimums

    def test_unmet_reports_native_units_not_normalised(self):
        fit = role_fit(player(speed=7.5), get_role("runner_in_behind"))
        actual, required = fit.unmet["max_speed"]
        assert (actual, required) == pytest.approx((7.5, 8.0))

    def test_inverted_minimum_means_at_most(self):
        """For reaction_time, lower is better, so a 'minimum' is a ceiling."""
        role = PlayRole("sharp", "Sharp", "", {"reaction_time": 1.0},
                        minimums={"reaction_time": 0.20})
        quick = PlayerState(1, Team.HOME, vec(0, 0), attributes=Attributes(),
                            capability=CapabilityProfile(reaction_time=0.16))
        slow = PlayerState(2, Team.HOME, vec(0, 0), attributes=Attributes(),
                           capability=CapabilityProfile(reaction_time=0.30))
        assert role_fit(quick, role).meets_minimums
        assert not role_fit(slow, role).meets_minimums

    def test_fatigue_can_push_a_player_below_a_physical_minimum(self):
        """Coverage is judged on present capability, not on a fresh-legs ideal."""
        role = get_role("runner_in_behind")
        assert role_fit(player(speed=8.3, stamina=1.0), role).meets_minimums
        assert not role_fit(player(speed=8.3, stamina=0.0), role).meets_minimums


class TestSlotGate:
    def test_a_gated_role_rejects_the_wrong_slot(self):
        keeper_role = get_role("sweeper_keeper")
        outfielder = player(slot=PositionalRole.CDM, passing_short=90, positioning=90)
        fit = role_fit(outfielder, keeper_role)
        assert fit.slot_ineligible
        assert not fit.meets_minimums
        assert "WRONG SLOT" in fit.explain()

    def test_a_gated_role_accepts_the_right_slot(self):
        keeper = player(slot=PositionalRole.GK, passing_short=60)
        assert not role_fit(keeper, get_role("sweeper_keeper")).slot_ineligible

    def test_ungated_roles_permit_any_slot(self):
        """The decoupling of play roles from slots is the point (D-018) — a centre-back
        outscoring a striker at box_target is the model working."""
        role = get_role("box_target")
        assert role.required_slots == frozenset()
        assert role.permits_slot(PositionalRole.LCB)
        assert not role_fit(player(slot=PositionalRole.LCB, heading=80), role).slot_ineligible

    def test_only_the_keeper_role_is_gated(self):
        gated = {key for key, role in ROLE_CATALOGUE.items() if role.required_slots}
        assert gated == {"sweeper_keeper"}


class TestCatalogue:
    def test_every_role_has_a_unique_key_matching_its_dict_key(self):
        assert all(key == role.key for key, role in ROLE_CATALOGUE.items())

    def test_every_role_is_documented(self):
        for role in ROLE_CATALOGUE.values():
            assert role.label and role.description

    def test_every_attribute_is_read_by_at_least_one_role(self):
        """An attribute with no consumer is a number that invites false precision."""
        read = {name for role in ROLE_CATALOGUE.values() for name in role.inputs}
        unread = set(Attributes.names()) - read
        assert unread == set(), f"attributes read by no role: {sorted(unread)}"

    def test_unknown_role_lookup_lists_the_catalogue(self):
        with pytest.raises(KeyError) as error:
            get_role("striker")
        assert "target_forward" in str(error.value)

    def test_minimums_are_sparse(self):
        """Every minimum can make a play infeasible, so they stay deliberately rare."""
        for role in ROLE_CATALOGUE.values():
            assert len(role.minimums) <= 2, role.key


class TestHelpers:
    def test_resolve_input_returns_native_and_normalised(self):
        native, normalised = resolve_input(player(crossing=75), "crossing")
        assert native == 75.0
        assert normalised == pytest.approx(0.75)

    def test_archetype_capability_differs_by_slot(self):
        assert archetype_capability(PositionalRole.RW).max_speed > archetype_capability(
            PositionalRole.CB
        ).max_speed

    def test_archetype_falls_back_for_unmapped_slots(self):
        assert archetype_capability(PositionalRole.CDM).max_speed == 7.8
        assert PositionalRole.CDM not in ARCHETYPE_CAPABILITY

    def test_rank_players_sorts_best_first_and_drops_failures(self):
        role = PlayRole("x", "X", "", {"crossing": 1.0}, minimums={"crossing": 50.0})
        squad = [player(1, crossing=90), player(2, crossing=30), player(3, crossing=70)]
        ranked = rank_players(squad, role)
        assert [fit.player_id for fit in ranked] == [1, 3]

    def test_rank_players_can_include_near_misses(self):
        role = PlayRole("x", "X", "", {"crossing": 1.0}, minimums={"crossing": 50.0})
        squad = [player(1, crossing=90), player(2, crossing=30)]
        assert len(rank_players(squad, role, eligible_only=False)) == 2

    def test_rank_players_excludes_unavailable(self):
        squad = [player(1, crossing=90, available=False), player(2, crossing=40)]
        assert [fit.player_id for fit in rank_players(squad, CROSSER)] == [2]
