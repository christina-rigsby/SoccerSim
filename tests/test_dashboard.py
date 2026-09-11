"""The estimators, scored against scenarios whose answer is known by construction.

This is the file that decides whether M2's inference actually works. Each scenario
plants a specific opponent behaviour and states it in :class:`ScenarioTruth`; the tests
assert the estimator recovers it — and, just as importantly, that it does *not* recover
behaviour that was not planted. An estimator that answers "man-marking" to everything
scores perfectly on a man-marking scenario, so the negative controls carry as much
weight as the positive ones.
"""

import pytest

from soccersim.dashboard import Dashboard, MarkingScheme
from soccersim.dashboard.book import PlayBook
from soccersim.dashboard.pressing import MIN_TRIGGER_RATE
from soccersim.domain.entities import Team
from soccersim.domain.fixtures import wing_overload_snapshot
from soccersim.scenarios import (
    ALL_SCENARIOS,
    MAN_ASSIGNMENTS,
    backpass_press_scenario,
    man_marking_scenario,
    passive_block_scenario,
    zonal_scenario,
)


def run(build):
    scenario = build()
    dashboard = Dashboard(our_team=Team.HOME)
    dashboard.observe_all(scenario.frames)
    return scenario, dashboard


class TestScenarios:
    @pytest.mark.parametrize("name", sorted(ALL_SCENARIOS))
    def test_every_scenario_produces_ordered_frames(self, name):
        scenario = ALL_SCENARIOS[name]()
        clocks = [frame.clock_seconds for frame in scenario.frames]
        assert clocks == sorted(clocks)
        assert len(scenario) > 100

    @pytest.mark.parametrize("name", sorted(ALL_SCENARIOS))
    def test_every_frame_is_physically_sane(self, name):
        scenario = ALL_SCENARIOS[name]()
        for frame in scenario.frames[::17]:
            assert len(frame.home.players) == 11
            assert len(frame.away.players) == 11
            for player in frame.all_players():
                assert frame.pitch.contains(player.position), player.player_id

    @pytest.mark.parametrize("name", sorted(ALL_SCENARIOS))
    def test_home_players_carry_roster_attributes(self, name):
        scenario = ALL_SCENARIOS[name]()
        frame = scenario.frames[0]
        assert all(p.attributes is not None for p in frame.home.players)
        assert all(p.attributes is None for p in frame.away.players), "opponents inferred"

    def test_a_non_chaining_pass_script_is_rejected(self):
        """A break in the chain teleports the ball, so the observer records a pass from
        the wrong origin while an earlier press may still be live."""
        from soccersim.scenarios import _pressing_scenario, ScenarioTruth

        with pytest.raises(ValueError, match="does not chain"):
            _pressing_scenario(
                [(10, 6, True), (8, 4, False)],
                presses=True, name="broken", description="",
                truth=ScenarioTruth(),
            )


class TestMarkingInference:
    def test_man_marking_is_recovered(self):
        scenario, dashboard = run(man_marking_scenario)
        estimate = dashboard.opponent_model().marking_scheme
        assert estimate.is_mature
        assert estimate.value is MarkingScheme.MAN
        assert estimate.value is scenario.truth.marking_scheme

    def test_every_planted_assignment_is_recovered_exactly(self):
        _, dashboard = run(man_marking_scenario)
        assignments = {
            defender: estimate.value
            for defender, estimate in dashboard.opponent_model().marking_assignments.items()
            if estimate.is_mature
        }
        assert assignments == MAN_ASSIGNMENTS

    def test_marker_of_answers_the_ranking_layers_question(self):
        """§5's mismatch_bonus wants 'who is on our man', or nothing."""
        _, dashboard = run(man_marking_scenario)
        model = dashboard.opponent_model()
        for defender, attacker in MAN_ASSIGNMENTS.items():
            assert model.marker_of(attacker) == defender

    def test_marker_of_returns_nothing_for_an_unmarked_player(self):
        _, dashboard = run(man_marking_scenario)
        unmarked = set(range(1, 12)) - set(MAN_ASSIGNMENTS.values())
        model = dashboard.opponent_model()
        assert all(model.marker_of(attacker) is None for attacker in unmarked)

    def test_zonal_is_not_mistaken_for_man_marking(self):
        """The negative control. Attackers run identical paths to the man-marking
        scenario, so anything reporting MAN here is keying on attacker movement rather
        than on defender behaviour."""
        scenario, dashboard = run(zonal_scenario)
        estimate = dashboard.opponent_model().marking_scheme
        assert estimate.is_mature
        assert estimate.value is MarkingScheme.ZONAL
        assert estimate.value is scenario.truth.marking_scheme
        assert estimate.detail["man_share"] < 0.35

    def test_zonal_produces_few_spurious_assignments(self):
        """A known limitation, quantified rather than tuned away: a zonal defender who
        happens to sit permanently close to one attacker and slide with the ball is
        genuinely indistinguishable from a marker by these signals (Q-027)."""
        _, dashboard = run(zonal_scenario)
        mature = [
            defender
            for defender, estimate in dashboard.opponent_model().marking_assignments.items()
            if estimate.is_mature
        ]
        assert len(mature) <= 3, f"too many false markers: {mature}"

    def test_zonal_defenders_get_zone_estimates(self):
        """§2 asks for zone boundaries when the scheme is zonal."""
        _, dashboard = run(zonal_scenario)
        zones = dashboard.opponent_model().zones
        assert len(zones) >= 6
        for centre, radius in zones.values():
            assert dashboard.observer.latest.pitch.contains(centre)
            assert radius >= 0.0

    def test_a_single_frame_yields_no_marking_estimate(self):
        dashboard = Dashboard()
        dashboard.observe(wing_overload_snapshot())
        estimate = dashboard.opponent_model().marking_scheme
        assert not estimate.is_mature
        assert estimate.mature_value is None


class TestPressingInference:
    def test_the_planted_trigger_is_recovered(self):
        scenario, dashboard = run(backpass_press_scenario)
        assert set(dashboard.opponent_model().press_triggers) == scenario.truth.press_triggers

    def test_the_trigger_rate_is_high_and_mature(self):
        _, dashboard = run(backpass_press_scenario)
        estimate = dashboard.pressing.trigger_estimate("back", "middle", dashboard.clock)
        assert estimate.is_mature
        assert estimate.value > 0.9

    def test_the_non_trigger_is_not_reported(self):
        """Forward passes from the same zone are seen just as often, so a count-based
        estimator would flag them. The conditional rate must not."""
        scenario, dashboard = run(backpass_press_scenario)
        estimate = dashboard.pressing.trigger_estimate("forward", "middle", dashboard.clock)
        assert estimate.is_mature, "the negative case must have real evidence behind it"
        assert estimate.value < MIN_TRIGGER_RATE
        for key in scenario.truth.press_non_triggers:
            assert key not in dashboard.opponent_model().press_triggers

    def test_a_passive_block_yields_no_triggers(self):
        """Same pass script, no pressing. Anything reported here is an artefact of pass
        frequency rather than a finding about the opponent."""
        scenario, dashboard = run(passive_block_scenario)
        assert dashboard.opponent_model().press_triggers == {}
        assert scenario.truth.press_triggers == frozenset()

    def test_a_passive_block_still_accumulates_trials(self):
        """Absence of a trigger must be an evidenced conclusion, not a lack of data."""
        _, dashboard = run(passive_block_scenario)
        estimate = dashboard.pressing.trigger_estimate("back", "middle", dashboard.clock)
        assert estimate.is_mature
        assert estimate.value == pytest.approx(0.0)

    def test_pressing_and_passive_differ_in_intensity_and_frequency(self):
        _, pressing = run(backpass_press_scenario)
        _, passive = run(passive_block_scenario)
        assert pressing.opponent_model().press_frequency.value > 0.2
        assert passive.opponent_model().press_frequency.value == pytest.approx(0.0)
        assert passive.opponent_model().press_intensity.value is None

    def test_frames_in_our_own_possession_do_not_dilute_frequency(self):
        """A team cannot press while holding the ball, so those frames are excluded
        rather than counted as 'not pressing'."""
        _, dashboard = run(backpass_press_scenario)
        assert dashboard.pressing.frequency(dashboard.clock).observations < len(
            backpass_press_scenario().frames
        )


class TestBook:
    def test_predictability_is_a_share_within_the_situation(self):
        book = PlayBook()
        here, elsewhere = ("final", "low", "open_play"), ("middle", "mid", "open_play")
        for t in range(4):
            book.record_use("overlap", here, t * 10.0)
        book.record_use("switch", here, 40.0)
        book.record_use("counter", elsewhere, 40.0)
        assert book.predictability("overlap", here, 40.0) > 0.7
        assert book.predictability("switch", here, 40.0) < 0.3
        assert book.predictability("overlap", elsewhere, 40.0) == 0.0

    def test_usage_decays_so_diversification_is_rewarded_within_a_match(self):
        book = PlayBook()
        situation = ("final", "low", "open_play")
        book.record_use("overlap", situation, 0.0)
        assert book.recent_usage("overlap", situation, 0.0) > 0.9
        assert book.recent_usage("overlap", situation, 3600.0) < 0.05

    def test_an_unused_play_is_never_predictable(self):
        assert PlayBook().predictability("x", ("a",), 0.0) == 0.0

    def test_success_rate_needs_evidence_before_it_can_be_acted_on(self):
        book = PlayBook()
        book.record_outcome("overlap", True, 0.0)
        assert book.success_rate("overlap", 0.0).mature_value is None
        for _ in range(6):
            book.record_outcome("overlap", True, 0.0)
        assert book.success_rate("overlap", 0.0).mature_value == pytest.approx(1.0)

    def test_outcomes_decay_far_more_slowly_than_usage(self):
        """§5 wants success rate to 'dominate over time as data accumulates', which it
        cannot do if the evidence keeps evaporating."""
        book = PlayBook()
        assert book._outcomes.half_life > book._usage.half_life * 5

    def test_dashboard_records_plays_against_the_live_situation(self):
        dashboard = Dashboard()
        dashboard.observe(wing_overload_snapshot())
        dashboard.record_play("overlap")
        assert dashboard.predictability("overlap") == pytest.approx(1.0)
        assert dashboard.predictability("switch_and_cross") == 0.0

    def test_recording_before_any_observation_is_an_error(self):
        with pytest.raises(ValueError, match="before observing"):
            Dashboard().record_play("overlap")


class TestDashboardSurface:
    def test_no_reports_before_any_observation(self):
        dashboard = Dashboard()
        assert dashboard.team_report() is None
        assert dashboard.opponent_model() is None
        assert dashboard.situation() is None

    def test_team_report_is_measurement_only(self):
        dashboard = Dashboard()
        dashboard.observe(wing_overload_snapshot())
        report = dashboard.team_report()
        assert report.shape.team is Team.HOME
        assert report.pressure_on_ball is not None
        assert report.situation == ("final", "low", "open_play")

    def test_opponent_model_describes_the_other_team(self):
        dashboard = Dashboard(our_team=Team.HOME)
        dashboard.observe(wing_overload_snapshot())
        assert dashboard.opponent_model().team is Team.AWAY

    def test_our_team_is_configurable(self):
        dashboard = Dashboard(our_team=Team.AWAY)
        dashboard.observe(wing_overload_snapshot())
        assert dashboard.opponent_model().team is Team.HOME
        assert dashboard.team_report().shape.team is Team.AWAY

    @pytest.mark.parametrize("name", sorted(ALL_SCENARIOS))
    def test_report_renders_for_every_scenario(self, name):
        _, dashboard = run(ALL_SCENARIOS[name])
        text = dashboard.report()
        assert "opponent" in text and "frames observed" in text

    def test_possessions_are_exposed(self):
        _, dashboard = run(backpass_press_scenario)
        assert dashboard.observer.current_possession is not None
        assert dashboard.observer.frames_observed == len(backpass_press_scenario().frames)
