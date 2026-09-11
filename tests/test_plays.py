"""Triggers, the play graph, the library, and instantiation.

The graph tests matter most: ``chain_depth`` and ``single_ball`` are read straight off
the dependency structure, and both are things §5 asks for that a flat step list could not
express.
"""

import numpy as np
import pytest

from soccersim.domain.actions import ACTIONS, get_action
from soccersim.domain.entities import Team
from soccersim.domain.fixtures import opponent_buildup_snapshot, wing_overload_snapshot
from soccersim.plays import (
    PlayError,
    anchor_from_spec,
    greedy_assignment,
    instantiate,
    load_library,
    play_from_spec,
    trigger_from_spec,
)
from soccersim.plays.anchors import PlayContext
from soccersim.plays.play import Play, PlayStep
from soccersim.plays.triggers import TRIGGER_KINDS, TriggerContext, TriggerError

WING_ASSIGN = {
    "wide_creator": 11, "overlap_runner": 5, "box_target": 10, "runner_in_behind": 9,
}


def step(key, role="wide_creator", action="move_to", anchor=None, **kwargs):
    return PlayStep(
        key=key, role=role, action=action,
        anchor=anchor_from_spec(anchor or {"kind": "ball"}),
        **kwargs,
    )


def make_play(steps, **kwargs):
    defaults = dict(
        key="test", label="Test", description="", objective="score", strategy="s",
    )
    return Play(steps=tuple(steps), **{**defaults, **kwargs})


class TestActions:
    def test_vocabulary_matches_the_design_doc_size(self):
        assert len(ACTIONS) == 26

    def test_releasing_actions_are_all_on_ball(self):
        assert all(
            spec.is_on_ball for spec in ACTIONS.values() if spec.releases_ball
        )

    def test_unknown_action_lists_the_vocabulary(self):
        with pytest.raises(KeyError, match="overhead_kick|vocabulary"):
            get_action("overhead_kick")


class TestTriggers:
    def context(self, state=None, **kwargs):
        play = PlayContext(state or wing_overload_snapshot(), Team.HOME, dict(WING_ASSIGN))
        return TriggerContext(play=play, clock=10.0, eligible_since=8.0, **kwargs)

    @pytest.mark.parametrize("kind", sorted(TRIGGER_KINDS))
    def test_every_kind_evaluates_to_a_bool(self, kind):
        defaults = {
            "elapsed": {"seconds": 1.0},
            "steps_done": {"steps": ["a"]},
            "ball_within": {"anchor": {"kind": "ball"}},
            "ball_played_by": {"role": "wide_creator"},
            "role_within": {"role": "wide_creator", "anchor": {"kind": "ball"}},
            "role_beyond": {"role": "wide_creator", "anchor": {"kind": "ball"}},
            "opponent_within": {"role": "wide_creator"},
            "lane_open": {"origin": {"kind": "ball"}, "target": {"kind": "goal"}},
            "control_above": {"anchor": {"kind": "ball"}},
            "pressure_above": {"role": "wide_creator"},
            "all_of": {"of": [{"kind": "immediately"}]},
            "any_of": {"of": [{"kind": "immediately"}]},
            "not": {"of": {"kind": "immediately"}},
        }
        trigger = trigger_from_spec({"kind": kind, **defaults.get(kind, {})})
        assert isinstance(trigger.evaluate(self.context()), bool)

    def test_elapsed_measures_from_eligibility(self):
        assert trigger_from_spec({"kind": "elapsed", "seconds": 1.5}).evaluate(self.context())
        assert not trigger_from_spec({"kind": "elapsed", "seconds": 5.0}).evaluate(self.context())

    def test_steps_done_requires_all_of_them(self):
        ctx = self.context(completed=frozenset({"a"}))
        assert trigger_from_spec({"kind": "steps_done", "steps": ["a"]}).evaluate(ctx)
        assert not trigger_from_spec({"kind": "steps_done", "steps": ["a", "b"]}).evaluate(ctx)

    def test_ball_played_by_needs_the_role_to_have_held_it(self):
        """A role that never received the ball and one that already released it look
        identical in a single snapshot, so play history is required."""
        spec = {"kind": "ball_played_by", "role": "box_target"}
        assert not trigger_from_spec(spec).evaluate(self.context())
        assert trigger_from_spec(spec).evaluate(
            self.context(held_ball=frozenset({"box_target"}))
        )

    def test_role_beyond_is_attacking_relative(self):
        far = {"kind": "role_beyond", "role": "wide_creator",
               "anchor": {"kind": "channel_depth", "flank": "centre", "progress": -0.9}}
        near = {"kind": "role_beyond", "role": "wide_creator",
                "anchor": {"kind": "goal"}}
        assert trigger_from_spec(far).evaluate(self.context())
        assert not trigger_from_spec(near).evaluate(self.context())

    def test_combinators(self):
        yes, no = {"kind": "immediately"}, {"kind": "elapsed", "seconds": 999.0}
        ctx = self.context()
        assert trigger_from_spec({"kind": "all_of", "of": [yes, yes]}).evaluate(ctx)
        assert not trigger_from_spec({"kind": "all_of", "of": [yes, no]}).evaluate(ctx)
        assert trigger_from_spec({"kind": "any_of", "of": [yes, no]}).evaluate(ctx)
        assert not trigger_from_spec({"kind": "not", "of": yes}).evaluate(ctx)

    def test_spec_validation(self):
        with pytest.raises(TriggerError, match="unknown trigger kind"):
            trigger_from_spec({"kind": "when_i_say_so"})
        with pytest.raises(TriggerError, match="unknown parameter"):
            trigger_from_spec({"kind": "elapsed", "secs": 1})
        with pytest.raises(TriggerError, match="non-empty list"):
            trigger_from_spec({"kind": "all_of", "of": []})

    def test_nested_specs_round_trip(self):
        spec = {
            "kind": "all_of",
            "of": [
                {"kind": "ball_within", "anchor": {"kind": "behind_line", "metres": 5.0,
                                                   "flank": "right", "line_count": 2},
                 "metres": 3.0},
                {"kind": "not", "of": {"kind": "immediately"}},
            ],
        }
        trigger = trigger_from_spec(spec)
        assert trigger.to_spec()["of"][0]["anchor"]["kind"] == "behind_line"
        assert trigger_from_spec(trigger.to_spec()).to_spec() == trigger.to_spec()


class TestPlayGraph:
    def test_chain_depth_is_the_longest_path(self):
        chained = make_play([
            step("a"), step("b", depends_on=("a",)), step("c", depends_on=("b",)),
        ])
        assert chained.chain_depth() == 3

    def test_parallel_steps_do_not_deepen_the_chain(self):
        """§5 penalises sequential chains, not player count: five independent runs are
        depth 1."""
        parallel = make_play([step(k) for k in "abcde"])
        assert parallel.chain_depth() == 1
        assert parallel.parallel_width() == 5

    def test_cycles_are_rejected(self):
        with pytest.raises(PlayError, match="cycle"):
            make_play([
                step("a", depends_on=("b",)), step("b", depends_on=("a",)),
            ])

    def test_self_dependency_is_rejected(self):
        with pytest.raises(PlayError, match="depends on itself"):
            make_play([step("a", depends_on=("a",))])

    def test_unknown_dependency_is_rejected(self):
        with pytest.raises(PlayError, match="unknown step"):
            make_play([step("a", depends_on=("ghost",))])

    def test_duplicate_step_keys_are_rejected(self):
        with pytest.raises(PlayError, match="duplicate step key"):
            make_play([step("a"), step("a")])

    def test_empty_play_is_rejected(self):
        with pytest.raises(PlayError, match="no steps"):
            make_play([])

    def test_terminal_steps_are_those_nothing_depends_on(self):
        play = make_play([
            step("a"), step("b", depends_on=("a",)), step("c", depends_on=("a",)),
        ])
        assert set(play.terminal_steps()) == {"b", "c"}

    def test_topological_order_respects_dependencies(self):
        play = make_play([step("c", depends_on=("b",)), step("b", depends_on=("a",)), step("a")])
        order = play.topological_order()
        assert order.index("a") < order.index("b") < order.index("c")

    def test_time_budget_accumulates_along_the_chain(self):
        play = make_play([
            step("a", timeout=2.0),
            step("b", timeout=3.0, depends_on=("a",)),
        ])
        assert play.time_budget("a") == pytest.approx(2.0)
        assert play.time_budget("b") == pytest.approx(5.0)

    def test_single_ball_conflict_when_nothing_orders_two_touches(self):
        """Two ball-touching steps conflict exactly when neither is an ancestor of the
        other — this caught a real error in the hand-authored three-pass counter."""
        conflicting = make_play([
            step("p1", action="pass", anchor={"kind": "goal"}),
            step("p2", action="pass", anchor={"kind": "goal"}, role="overlap_runner"),
        ])
        assert conflicting.concurrent_on_ball() == [("p1", "p2")]

    def test_no_conflict_when_the_touches_are_chained(self):
        chained = make_play([
            step("p1", action="pass", anchor={"kind": "goal"}),
            step("p2", action="pass", anchor={"kind": "goal"},
                 role="overlap_runner", depends_on=("p1",)),
        ])
        assert chained.concurrent_on_ball() == []

    def test_structure_report_is_weight_free(self):
        """Structural metrics only; turning them into penalties waits for Q-001."""
        structure = make_play([step("a")]).structure()
        assert set(structure) == {
            "steps", "roles", "chain_depth", "parallel_width", "terminal_steps",
            "on_ball_steps", "single_ball_conflicts", "total_time_budget",
        }
        assert not any("weight" in k or "cost" in k or "score" in k for k in structure)


class TestStepValidation:
    def test_action_needing_an_anchor_must_have_one(self):
        with pytest.raises(PlayError, match="needs an anchor"):
            PlayStep(key="a", role="wide_creator", action="pass")

    def test_action_taking_no_anchor_must_not_have_one(self):
        with pytest.raises(PlayError, match="takes no anchor"):
            step("a", action="hold_position")

    def test_unknown_role_lists_the_catalogue(self):
        with pytest.raises(PlayError, match="unknown play role"):
            step("a", role="libero")

    def test_unknown_action_is_rejected(self):
        with pytest.raises(KeyError):
            step("a", action="rabona")

    def test_non_positive_timeout_is_rejected(self):
        with pytest.raises(PlayError, match="timeout must be positive"):
            step("a", timeout=0.0)


class TestLibrary:
    def test_the_shipped_library_loads(self):
        library = load_library()
        assert len(library) == 7

    def test_every_shipped_play_is_structurally_sound(self):
        for play in load_library():
            assert play.concurrent_on_ball() == [], play.key
            assert play.chain_depth() >= 1
            assert play.terminal_steps()
            assert play.description and play.source

    def test_the_library_covers_both_phases(self):
        library = load_library()
        assert library.in_possession(True)
        assert library.in_possession(False), "presses are out-of-possession plays"

    def test_the_library_covers_every_strategy_named_in_the_doc(self):
        strategies = {play.strategy for play in load_library()}
        assert strategies == {"wing_overload", "counter_attack", "high_press"}

    def test_every_play_uses_roles_from_the_m0_5_catalogue(self):
        from soccersim.domain.roles import ROLE_CATALOGUE

        assert load_library().roles_used() <= set(ROLE_CATALOGUE)

    def test_presses_are_shallower_than_counters(self):
        """Chain depth should reflect football reality: a press is parallel pressure, a
        three-pass counter is a sequence of handoffs."""
        library = load_library()
        assert library.get("trigger_press").chain_depth() < library.get(
            "three_pass_counter"
        ).chain_depth()

    def test_plays_round_trip_through_their_spec(self):
        for play in load_library():
            assert play_from_spec(play.to_spec()).to_spec() == play.to_spec()

    def test_unknown_play_lists_the_library(self):
        with pytest.raises(KeyError, match="overlap_right"):
            load_library().get("tiki_taka")

    def test_missing_directory_is_reported(self):
        with pytest.raises(PlayError, match="no play directory"):
            load_library("/nonexistent/plays")


class TestInstantiation:
    def test_resolves_anchors_into_waypoints(self):
        play = load_library().get("overlap_right")
        instantiated = instantiate(play, wing_overload_snapshot(), WING_ASSIGN, Team.HOME)
        assert len(instantiated.steps) == len(play.steps)
        assert instantiated.waypoints

    def test_releasing_steps_get_no_player_waypoint(self):
        """A pass's anchor is where the *ball* goes. Treating it as a player destination
        made the crosser run to the near post and collide with the player attacking it."""
        play = load_library().get("overlap_right")
        instantiated = instantiate(play, wing_overload_snapshot(), WING_ASSIGN, Team.HOME)
        by_key = {s.step.key: s for s in instantiated.steps}
        assert by_key["cross"].target is not None
        assert by_key["cross"].waypoint is None
        assert by_key["overlap"].waypoint is not None

    def test_sustained_steps_get_no_waypoint(self):
        play = load_library().get("trigger_press")
        state = opponent_buildup_snapshot()
        assignment = greedy_assignment(play, state, Team.HOME).assignment
        instantiated = instantiate(play, state, assignment, Team.HOME)
        shadow = next(s for s in instantiated.steps if s.step.key == "shadow_return")
        assert shadow.step.action_spec.sustained
        assert shadow.waypoint is None

    def test_missing_role_is_rejected(self):
        play = load_library().get("overlap_right")
        with pytest.raises(PlayError, match="unassigned"):
            instantiate(play, wing_overload_snapshot(), {"wide_creator": 11}, Team.HOME)

    def test_one_player_cannot_fill_two_roles(self):
        """Which is the whole reason §4 solves an assignment problem."""
        play = load_library().get("overlap_right")
        clashing = dict(WING_ASSIGN, runner_in_behind=10)
        with pytest.raises(PlayError, match="distinct players"):
            instantiate(play, wing_overload_snapshot(), clashing, Team.HOME)

    def test_possession_mismatch_is_a_violation(self):
        press = load_library().get("trigger_press")
        state = wing_overload_snapshot()  # we have the ball
        assignment = {
            "first_presser": 10, "ball_winner": 7,
            "deep_lying_passer": 6, "ball_playing_defender": 3,
        }
        constraints = [
            v.constraint
            for v in instantiate(press, state, assignment, Team.HOME).violations()
        ]
        assert "possession_state" in constraints

    def test_unresolvable_anchors_are_reported_not_raised(self):
        press = load_library().get("trigger_press")
        state = wing_overload_snapshot()
        assignment = {
            "first_presser": 10, "ball_winner": 7,
            "deep_lying_passer": 6, "ball_playing_defender": 3,
        }
        instantiated = instantiate(press, state, assignment, Team.HOME)
        assert instantiated.anchor_errors
        assert any(
            v.constraint == "anchor_unresolvable" for v in instantiated.violations()
        )

    def test_offside_is_not_checked_at_selection_time(self):
        """§5 judges offside "at the moment of the pass". A run beyond the line is legal
        to make, so checking it here would reject nearly every counter-attack."""
        play = load_library().get("direct_vertical")
        state = opponent_buildup_snapshot()
        assignment = greedy_assignment(play, state, Team.HOME).assignment
        if not assignment or set(play.roles()) - set(assignment):
            pytest.skip("greedy assignment could not fill this play here")
        constraints = [
            v.constraint
            for v in instantiate(play, state, assignment, Team.HOME).violations()
        ]
        assert "offside" not in constraints

    def test_a_press_play_is_feasible_out_of_possession(self):
        play = load_library().get("trigger_press")
        state = opponent_buildup_snapshot()
        assignment = greedy_assignment(play, state, Team.HOME).assignment
        instantiated = instantiate(play, state, assignment, Team.HOME)
        assert instantiated.is_feasible, instantiated.describe()


class TestGreedyAssignment:
    def test_fills_a_play_when_candidates_exist(self):
        play = load_library().get("switch_and_cross")
        result = greedy_assignment(play, wing_overload_snapshot(), Team.HOME)
        assert result.complete
        assert len(set(result.assignment.values())) == len(result.assignment)

    def test_reports_roles_it_cannot_fill(self):
        """runner_in_behind needs 8 m/s, which nobody clears at 62 minutes."""
        play = load_library().get("overlap_right")
        result = greedy_assignment(play, wing_overload_snapshot(), Team.HOME)
        assert "runner_in_behind" in result.unfilled
        assert not result.complete

    def test_prefers_a_player_who_has_practised_the_role(self):
        play = load_library().get("trigger_press")
        state = opponent_buildup_snapshot()
        result = greedy_assignment(play, state, Team.HOME)
        presser = state.player(result.assignment["first_presser"])
        assert presser.has_practised("first_presser")
