"""Roster loading.

A squad file is hand-edited JSON, so almost every test here is about *rejecting* bad
input with a message that names the offender. A silently-ignored typo in a roster is a
bug you find three milestones later, when a role mysteriously has no takers.
"""

import json

import pytest

from soccersim.domain.attributes import Attributes, Foot
from soccersim.domain.entities import PositionalRole, Team
from soccersim.domain.pitch import vec
from soccersim.domain.roster import (
    DEFAULT_ROSTER_PATH,
    Roster,
    RosterError,
    load_roster,
    parse_roster,
)


def minimal(**overrides):
    player = {
        "player_id": 1,
        "positional_role": "RW",
        "attributes": {"crossing": 70},
    }
    player.update(overrides)
    return {"team": "home", "name": "Test", "players": [player]}


class TestValidation:
    def test_loads_a_minimal_roster(self):
        roster = parse_roster(minimal())
        assert len(roster) == 1
        assert roster.entry(1).positional_role is PositionalRole.RW

    def test_rejects_unknown_top_level_key(self):
        data = minimal()
        data["formation"] = "4-3-3"
        with pytest.raises(RosterError, match="unknown key"):
            parse_roster(data)

    def test_rejects_unknown_player_key(self):
        with pytest.raises(RosterError, match="unknown key"):
            parse_roster(minimal(nickname="Speedy"))

    def test_rejects_unknown_attribute(self):
        with pytest.raises(RosterError, match="unknown attribute"):
            parse_roster(minimal(attributes={"pace": 90}))

    def test_rejects_off_scale_attribute(self):
        with pytest.raises(RosterError, match="outside the"):
            parse_roster(minimal(attributes={"crossing": 140}))

    def test_rejects_unknown_positional_role(self):
        with pytest.raises(RosterError, match="unknown positional_role"):
            parse_roster(minimal(positional_role="SWEEPER"))

    def test_rejects_unknown_foot(self):
        with pytest.raises(RosterError, match="unknown foot"):
            parse_roster(minimal(foot="either"))

    def test_rejects_unknown_practised_role(self):
        """The most valuable typo check: a misspelled role would silently never match."""
        with pytest.raises(RosterError, match="unknown practised role"):
            parse_roster(minimal(practised_roles=["winger"]))

    def test_rejects_missing_player_id(self):
        data = minimal()
        del data["players"][0]["player_id"]
        with pytest.raises(RosterError, match="missing required key 'player_id'"):
            parse_roster(data)

    def test_rejects_missing_positional_role(self):
        data = minimal()
        del data["players"][0]["positional_role"]
        with pytest.raises(RosterError, match="missing required key 'positional_role'"):
            parse_roster(data)

    def test_rejects_duplicate_player_id(self):
        data = minimal()
        data["players"].append(dict(data["players"][0]))
        with pytest.raises(RosterError, match="duplicate player_id"):
            parse_roster(data)

    def test_rejects_empty_player_list(self):
        with pytest.raises(RosterError, match="non-empty list"):
            parse_roster({"team": "home", "players": []})

    def test_rejects_non_positive_physical_value(self):
        with pytest.raises(RosterError, match="must be positive"):
            parse_roster(minimal(physical={"max_speed": 0.0}))

    def test_rejects_unknown_physical_key(self):
        with pytest.raises(RosterError, match="unknown key"):
            parse_roster(minimal(physical={"stamina": 1.0}))

    def test_rejects_an_away_roster(self):
        """Opponent attributes are inferred, not authored (D-021 / Q-008)."""
        data = minimal()
        data["team"] = "away"
        with pytest.raises(RosterError, match="inferred from observed play"):
            parse_roster(data)

    def test_error_message_names_the_player(self):
        with pytest.raises(RosterError, match="Winger"):
            parse_roster(minimal(name="Winger", attributes={"crossing": 500}))

    def test_missing_file_explains_what_to_do(self, tmp_path):
        with pytest.raises(RosterError, match="Copy the template"):
            load_roster(tmp_path / "absent.json")

    def test_invalid_json_is_reported_as_such(self, tmp_path):
        path = tmp_path / "broken.json"
        path.write_text("{not json")
        with pytest.raises(RosterError, match="invalid JSON"):
            load_roster(path)


class TestDefaultsAndComments:
    def test_underscore_keys_are_treated_as_comments(self):
        data = minimal(_note="this player is a placeholder")
        data["_README"] = ["a comment"]
        assert len(parse_roster(data)) == 1

    def test_absent_physical_falls_back_to_the_positional_archetype(self):
        roster = parse_roster(minimal(positional_role="RW"))
        assert roster.entry(1).capability.max_speed == 8.6  # QUICK
        central = parse_roster(minimal(positional_role="CDM"))
        assert central.entry(1).capability.max_speed == 7.8  # AVERAGE

    def test_partial_physical_keeps_archetype_for_the_rest(self):
        roster = parse_roster(minimal(positional_role="RW", physical={"max_speed": 9.0}))
        assert roster.entry(1).capability.max_speed == 9.0
        assert roster.entry(1).capability.max_accel == 7.0  # QUICK's value

    def test_absent_attributes_are_defaulted_and_reported(self):
        """A defaulted 50 looks identical to an authored one, so it must be surfaced."""
        roster = parse_roster(minimal(attributes={"crossing": 70}))
        defaulted = roster.defaulted_attributes[1]
        assert "finishing" in defaulted
        assert "crossing" not in defaulted
        assert roster.entry(1).attributes.finishing == 50.0

    def test_fully_authored_attributes_report_nothing_defaulted(self):
        full = {name: 60 for name in Attributes.names()}
        roster = parse_roster(minimal(attributes=full))
        assert roster.defaulted_attributes == {}

    def test_foot_defaults_to_right(self):
        assert parse_roster(minimal()).entry(1).foot is Foot.RIGHT


class TestRosterApi:
    def test_entry_lookup_error_lists_the_ids(self):
        roster = parse_roster(minimal())
        with pytest.raises(KeyError, match=r"\[1\]"):
            roster.entry(99)

    def test_by_slot_filters(self):
        roster = load_roster()
        assert [e.player_id for e in roster.by_slot(PositionalRole.GK)] == [1]

    def test_to_player_state_merges_constant_and_instant_data(self):
        entry = parse_roster(minimal()).entry(1)
        state = entry.to_player_state(Team.HOME, vec(10, 5), velocity=vec(3, 0), stamina=0.6)
        assert state.position.tolist() == [10.0, 5.0]
        assert state.stamina == 0.6
        assert state.positional_role is PositionalRole.RW
        assert state.attributes is not None

    def test_player_states_builds_from_a_snapshot(self):
        roster = load_roster()
        states = roster.player_states({1: {"position": (-50, 0)}, 10: {"position": (0, 0)}})
        assert {s.player_id for s in states} == {1, 10}
        assert all(s.team is Team.HOME for s in states)

    def test_player_states_rejects_an_unknown_id(self):
        """A typo'd id would otherwise conjure a ghost player."""
        with pytest.raises(KeyError, match="no player 77"):
            load_roster().player_states({77: {"position": (0, 0)}})

    def test_with_attributes_returns_an_adjusted_copy(self):
        roster = load_roster()
        tweaked = roster.with_attributes(11, crossing=99)
        assert tweaked.entry(11).attributes.crossing == 99
        assert roster.entry(11).attributes.crossing != 99, "original must be unchanged"

    def test_iteration_and_length_agree(self):
        roster = load_roster()
        assert len(list(roster)) == len(roster)

    def test_summary_mentions_every_player(self):
        roster = load_roster()
        summary = roster.summary()
        assert all(str(e.positional_role.value) in summary for e in roster)


class TestShippedRoster:
    """Guards on the template that ships with the repo, so an edit that breaks the
    fixtures fails here rather than in some unrelated geometry test."""

    def test_the_default_roster_loads(self):
        assert len(load_roster()) == 11

    def test_it_covers_exactly_the_fixture_player_ids(self):
        assert sorted(e.player_id for e in load_roster()) == list(range(1, 12))

    def test_it_has_exactly_one_goalkeeper(self):
        keepers = [e for e in load_roster() if e.positional_role.is_goalkeeper]
        assert len(keepers) == 1

    def test_every_attribute_is_authored_not_defaulted(self):
        assert load_roster().defaulted_attributes == {}

    def test_it_is_valid_json_with_a_readme(self):
        data = json.loads(DEFAULT_ROSTER_PATH.read_text())
        assert "_README" in data, "the template must explain itself to whoever edits it"
