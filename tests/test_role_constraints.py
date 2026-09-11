"""Role-based hard constraints — §5's ``eligibility`` and ``min_role_coverage``.

The distinction under test is the one §5 insists on: an *uncovered* role makes a play
infeasible outright, which is "distinct from 'role filled but poorly matched,' which is
soft". So these tests check pruning behaviour and diagnostics, never scores.
"""

import pytest

from soccersim.constraints.feasibility import Violation
from soccersim.constraints.roles import (
    check_eligibility,
    check_min_role_coverage,
    check_role_requirements,
    role_coverage,
    squad_coverage,
)
from soccersim.domain.attributes import Attributes
from soccersim.domain.entities import (
    CapabilityProfile,
    PlayerState,
    PositionalRole,
    Team,
)
from soccersim.domain.fixtures import wing_overload_snapshot
from soccersim.domain.pitch import vec
from soccersim.domain.roles import ROLE_CATALOGUE, PlayRole, get_role
from soccersim.domain.roster import load_roster

GATED = PlayRole(
    "gated", "Gated", "", {"crossing": 1.0}, minimums={"crossing": 60.0}
)


def player(player_id=1, available=True, speed=8.0, slot=PositionalRole.RW, **attributes):
    return PlayerState(
        player_id=player_id,
        team=Team.HOME,
        position=vec(0, 0),
        positional_role=slot,
        capability=CapabilityProfile(max_speed=speed, max_accel=6.5, reaction_time=0.2),
        available=available,
        attributes=Attributes(**attributes),
    )


def squad():
    roster = load_roster()
    return [entry.to_player_state(Team.HOME, vec(0, 0)) for entry in roster]


class TestEligibility:
    def test_available_player_passes(self):
        assert check_eligibility(player(), GATED) is None

    def test_unavailable_player_is_a_violation(self):
        found = check_eligibility(player(available=False), GATED)
        assert isinstance(found, Violation)
        assert found.constraint == "eligibility"
        assert "unavailable" in found.detail

    def test_the_message_names_the_role(self):
        found = check_eligibility(player(available=False), GATED)
        assert "gated" in found.detail


class TestCoverage:
    def test_covered_when_someone_clears_the_bar(self):
        assert check_min_role_coverage([player(crossing=70)], GATED) is None

    def test_uncovered_when_nobody_does(self):
        found = check_min_role_coverage([player(crossing=50)], GATED)
        assert found is not None
        assert found.constraint == "min_role_coverage"

    def test_the_violation_names_the_closest_miss_and_the_gap(self):
        """'Nobody can do this' is not actionable; the margin is."""
        found = check_min_role_coverage(
            [player(1, crossing=20), player(2, crossing=58)], GATED
        )
        assert "player 2" in found.detail
        assert "58" in found.detail and "60" in found.detail

    def test_unavailable_players_cannot_provide_coverage(self):
        found = check_min_role_coverage([player(crossing=90, available=False)], GATED)
        assert found is not None

    def test_unavailable_players_are_not_listed_as_near_misses(self):
        """Being suspended is not a capability shortfall; conflating them misleads."""
        coverage = role_coverage([player(crossing=90, available=False)], GATED)
        assert coverage.near_misses == []
        assert coverage.candidates == []

    def test_empty_squad_is_uncovered(self):
        assert check_min_role_coverage([], GATED) is not None

    def test_candidates_are_sorted_best_first(self):
        coverage = role_coverage(
            [player(1, crossing=65), player(2, crossing=95), player(3, crossing=80)], GATED
        )
        assert [fit.player_id for fit in coverage.candidates] == [2, 3, 1]

    def test_depth_counts_only_qualifying_players(self):
        coverage = role_coverage(
            [player(1, crossing=95), player(2, crossing=10)], GATED
        )
        assert coverage.depth == 1
        assert len(coverage.near_misses) == 1

    def test_closest_miss_ranks_by_relative_shortfall(self):
        """0.1 m/s short of 8.0 is closer than 20 points short of 60."""
        role = PlayRole(
            "multi", "Multi", "", {"crossing": 1.0},
            minimums={"crossing": 60.0, "max_speed": 8.0},
        )
        narrow = player(1, crossing=70, speed=7.9)
        wide = player(2, crossing=40, speed=8.5)
        coverage = role_coverage([narrow, wide], role)
        assert coverage.closest_miss().player_id == 1

    def test_closest_miss_skips_slot_only_failures(self):
        """No margin describes a wrong-slot failure, and no improvement fixes it."""
        outfielder = player(slot=PositionalRole.CDM, passing_short=99, positioning=99)
        coverage = role_coverage([outfielder], get_role("sweeper_keeper"))
        assert not coverage.is_covered
        assert coverage.closest_miss() is None

    def test_slot_gate_makes_a_role_uncoverable_without_the_right_slot(self):
        outfielders = [player(i, slot=PositionalRole.CDM, passing_short=95) for i in (1, 2)]
        assert check_min_role_coverage(outfielders, get_role("sweeper_keeper")) is not None


class TestRoleRequirements:
    def test_a_coverable_role_set_produces_no_violations(self):
        assert check_role_requirements(squad(), ["overlap_runner", "wide_creator"]) == []

    def test_reports_every_uncovered_role_not_just_the_first(self):
        weak = [player(i, crossing=10, speed=6.0, slot=PositionalRole.CDM) for i in range(1, 6)]
        found = check_role_requirements(weak, ["runner_in_behind", "target_forward"])
        assert len(found) == 2
        assert all(v.constraint == "min_role_coverage" for v in found)

    def test_duplicate_role_keys_are_collapsed(self):
        found = check_role_requirements(squad(), ["overlap_runner", "overlap_runner"])
        assert found == []

    def test_more_roles_than_players_is_a_player_count_violation(self):
        found = check_role_requirements(
            [player(1, crossing=90)], ["overlap_runner", "wide_creator"]
        )
        assert any(v.constraint == "player_count" for v in found)

    def test_unavailable_players_do_not_count_toward_player_count(self):
        available = [player(1, crossing=90)]
        benched = [player(2, crossing=90, available=False)]
        found = check_role_requirements(available + benched, ["wide_creator", "overlap_runner"])
        assert any(v.constraint == "player_count" for v in found)

    def test_unknown_role_key_is_rejected(self):
        with pytest.raises(KeyError, match="unknown play role"):
            check_role_requirements(squad(), ["striker"])


class TestShippedSquadCoverage:
    """Properties of the template roster. These are the demonstration that the hard
    check works, and they guard the template against an edit that quietly breaks it."""

    def test_every_catalogue_role_is_coverable(self):
        coverage = squad_coverage(squad())
        uncovered = [key for key, cover in coverage.items() if not cover.is_covered]
        assert uncovered == [], f"uncovered roles: {uncovered}"

    def test_only_the_actual_keeper_can_be_the_sweeper_keeper(self):
        coverage = squad_coverage(squad(), ["sweeper_keeper"])["sweeper_keeper"]
        assert coverage.depth == 1
        assert coverage.best.player_id == 1

    def test_the_deliberate_near_miss_is_reported(self):
        """#9's 7.9 m/s sits just under runner_in_behind's 8.0 floor by design."""
        coverage = squad_coverage(squad(), ["runner_in_behind"])["runner_in_behind"]
        misses = {fit.player_id: fit.unmet for fit in coverage.near_misses}
        assert misses[9]["max_speed"] == pytest.approx((7.9, 8.0))

    def test_the_right_footed_right_winger_cannot_invert(self):
        """inverted_winger gates on weak_foot, so footedness genuinely excludes."""
        coverage = squad_coverage(squad(), ["inverted_winger"])["inverted_winger"]
        assert 11 not in {fit.player_id for fit in coverage.candidates}
        assert 9 in {fit.player_id for fit in coverage.candidates}

    def test_squad_coverage_defaults_to_the_whole_catalogue(self):
        assert set(squad_coverage(squad())) == set(ROLE_CATALOGUE)


class TestAgainstFixtures:
    def test_home_players_can_be_matched_to_roles(self):
        state = wing_overload_snapshot()
        assert check_role_requirements(state.home.players, ["overlap_runner"]) == []

    def test_matching_an_opponent_raises_rather_than_inventing_numbers(self):
        """An away player has no authored attributes, and guessing would be worse than
        failing (D-021 / Q-008)."""
        state = wing_overload_snapshot()
        with pytest.raises(ValueError, match="inferred from observed play"):
            check_role_requirements(state.away.players, ["overlap_runner"])

    def test_fatigue_in_a_late_game_fixture_can_thin_coverage(self):
        """The wing-overload snapshot is at 62 minutes with stamina down to 0.61, so
        coverage there should be no better than for a fresh squad."""
        late = squad_coverage(wing_overload_snapshot().home.players, ["runner_in_behind"])
        fresh = squad_coverage(squad(), ["runner_in_behind"])
        assert late["runner_in_behind"].depth <= fresh["runner_in_behind"].depth
