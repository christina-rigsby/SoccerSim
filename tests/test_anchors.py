"""Spatial anchors — the mechanism behind "flexible, not (x1,y1) to (x2,y2)".

The mirror tests carry the most weight. ``fixtures.mirrored`` is a *reflection*, and
reflections swap left and right, so a flank-relative anchor must map right to left while
a direction-only anchor mirrors in ``x`` alone. Getting that wrong silently mirrors every
play, which is the class of bug Q-011 exists to catch — and did catch here, twice.
"""

import numpy as np
import pytest

from soccersim.domain.entities import Team
from soccersim.domain.fixtures import (
    mirrored,
    opponent_buildup_snapshot,
    wing_overload_snapshot,
)
from soccersim.plays.anchors import (
    ANCHOR_KINDS,
    AnchorError,
    BehindLine,
    PlayContext,
    anchor_from_spec,
    channel_centre_y,
    flank_sign,
)

ASSIGN = {
    "wide_creator": 11, "overlap_runner": 5, "box_target": 10,
    "runner_in_behind": 9, "deep_lying_passer": 6,
}


def context(state=None, team=Team.HOME, assignment=None):
    return PlayContext(
        state or wing_overload_snapshot(), team, assignment or dict(ASSIGN)
    )


def xflip(point):
    return np.array([-point[0], point[1]])


class TestFlankConvention:
    def test_left_and_right_are_team_relative(self):
        assert flank_sign("left", 1) == -1.0
        assert flank_sign("right", 1) == 1.0
        assert flank_sign("left", -1) == 1.0
        assert flank_sign("right", -1) == -1.0

    def test_centre_has_no_side(self):
        assert flank_sign("centre", 1) == 0.0

    def test_matches_the_fixtures_own_role_labels(self):
        """Home attacks +x with its left-back at negative y, so the convention has to
        agree with the squad data or every flank parameter is mirrored."""
        state = wing_overload_snapshot()
        left_back = next(p for p in state.home.players if p.positional_role.value == "LB")
        assert np.sign(left_back.position[1]) == flank_sign("left", 1)
        away_left_back = next(p for p in state.away.players if p.positional_role.value == "LB")
        assert np.sign(away_left_back.position[1]) == flank_sign("left", -1)

    def test_unknown_flank_is_rejected(self):
        with pytest.raises(AnchorError, match="unknown flank"):
            flank_sign("wing", 1)

    def test_channel_centres_are_ordered_and_mirror(self):
        pitch = wing_overload_snapshot().pitch
        right = channel_centre_y("right", pitch, 1)
        right_half = channel_centre_y("right_half", pitch, 1)
        assert right > right_half > 0
        assert channel_centre_y("right", pitch, -1) == -right


class TestResolution:
    @pytest.mark.parametrize("kind", sorted(ANCHOR_KINDS))
    def test_every_kind_resolves_or_explains(self, kind):
        """No anchor may fail obscurely; either it resolves or it says why not."""
        defaults = {
            "player": {"role": "wide_creator"},
            "opponent": {"which": "nearest_to_ball"},
            "offset": {"base": {"kind": "ball"}},
        }
        anchor = anchor_from_spec({"kind": kind, **defaults.get(kind, {})})
        try:
            point = anchor.resolve(context())
        except AnchorError as error:
            assert str(error)
            return
        assert point.shape == (2,)

    def test_line_anchors_land_in_the_opponents_half(self):
        """The bug this guards: DefensiveLine.height is the *opponent's* progress, so
        inverting it with our direction put anchors in our own half."""
        ctx = context()
        assert ctx.opponent_line_x() > 30.0
        gap = anchor_from_spec({"kind": "line_gap"}).resolve(ctx)
        assert gap[0] > 30.0

    def test_behind_line_sits_beyond_the_line(self):
        ctx = context()
        line_x = ctx.opponent_line_x()
        point = BehindLine(metres=6.0, flank="centre").resolve(ctx)
        assert point[0] == pytest.approx(line_x + 6.0)

    def test_behind_line_can_resolve_out_of_bounds(self):
        """Deliberately unclamped: no space behind a line near its own goal line means
        the play does not fit, and pitch_bounds should say so."""
        ctx = context()
        point = BehindLine(metres=20.0, flank="centre").resolve(ctx)
        assert not ctx.pitch.contains(point)

    def test_box_target_stays_onside(self):
        """A striker attacking a cross is onside by definition; a fixed six-yard-box
        target is offside against any deep block, and every cross aborted until this
        anchor became line-aware."""
        ctx = context()
        onside = anchor_from_spec({"kind": "box_target", "spot": "near"}).resolve(ctx)
        raw = anchor_from_spec(
            {"kind": "box_target", "spot": "near", "onside": False}
        ).resolve(ctx)
        assert onside[0] < raw[0]
        assert onside[0] <= ctx.opponent_line_x(2)

    def test_box_target_near_and_far_follow_the_ball_side(self):
        ctx = context()
        near = anchor_from_spec({"kind": "box_target", "spot": "near"}).resolve(ctx)
        far = anchor_from_spec({"kind": "box_target", "spot": "far"}).resolve(ctx)
        ball_y = ctx.state.ball.position[1]
        assert np.sign(near[1]) == np.sign(ball_y)
        assert np.sign(far[1]) == -np.sign(ball_y)

    def test_line_gap_can_be_restricted_to_a_flank(self):
        ctx = context()
        right = anchor_from_spec({"kind": "line_gap", "flank": "right"}).resolve(ctx)
        assert right[1] * flank_sign("right", ctx.attacking_direction) > 0

    def test_max_control_respects_its_zone(self):
        ctx = context()
        point = anchor_from_spec(
            {"kind": "max_control", "third": "final", "flank": "right"}
        ).resolve(ctx)
        assert ctx.pitch.third(point, ctx.attacking_direction) == "final"
        assert ctx.pitch.channel(point) == "right"

    def test_max_control_without_a_zone_is_usually_useless(self):
        """Unrestricted, the most-controlled point is next to our own keeper — which is
        why the zone parameters exist."""
        ctx = context()
        point = anchor_from_spec({"kind": "max_control"}).resolve(ctx)
        assert ctx.attacking_direction * point[0] < 0

    def test_offset_is_attacking_relative_and_composable(self):
        ctx = context()
        base = anchor_from_spec({"kind": "ball"}).resolve(ctx)
        shifted = anchor_from_spec(
            {"kind": "offset", "base": {"kind": "ball"}, "forward": 5.0, "lateral": 2.0}
        ).resolve(ctx)
        assert shifted[0] == pytest.approx(base[0] + 5.0 * ctx.attacking_direction)

    def test_cover_shadow_edge_is_past_the_nearest_defender(self):
        ctx = context()
        point = anchor_from_spec({"kind": "cover_shadow_edge"}).resolve(ctx)
        ball = np.asarray(ctx.state.ball.position, dtype=float)
        nearest = min(
            ctx.state.opponents_of(Team.HOME).available(),
            key=lambda p: float(np.linalg.norm(p.position - ball)),
        )
        assert np.linalg.norm(point - ball) > np.linalg.norm(nearest.position - ball)

    def test_opponent_carrier_refuses_when_we_have_the_ball(self):
        with pytest.raises(AnchorError, match="our own team has the ball"):
            anchor_from_spec({"kind": "opponent", "which": "carrier"}).resolve(context())

    def test_opponent_carrier_resolves_out_of_possession(self):
        ctx = context(opponent_buildup_snapshot(), Team.HOME, {"first_presser": 10})
        point = anchor_from_spec({"kind": "opponent", "which": "carrier"}).resolve(ctx)
        assert np.allclose(point, ctx.state.player(23).position)

    def test_unassigned_role_is_reported_clearly(self):
        with pytest.raises(AnchorError, match="not assigned"):
            anchor_from_spec({"kind": "player", "role": "target_forward"}).resolve(context())


class TestMirroring:
    """Q-011 for the play layer."""

    @pytest.mark.parametrize(
        "spec",
        [
            {"kind": "line_gap"},
            {"kind": "goal"},
            {"kind": "ball"},
            {"kind": "box_target", "spot": "near"},
            {"kind": "player", "role": "wide_creator"},
        ],
    )
    def test_direction_only_anchors_mirror_in_x(self, spec):
        original = anchor_from_spec(spec).resolve(context(wing_overload_snapshot()))
        flipped = anchor_from_spec(spec).resolve(context(mirrored(wing_overload_snapshot())))
        assert np.allclose(xflip(original), flipped, atol=0.01)

    @pytest.mark.parametrize(
        "kind,extra",
        [
            ("behind_line", {"metres": 8.0}),
            ("channel_depth", {"progress": 0.7}),
            ("max_control", {"third": "final"}),
        ],
    )
    def test_flank_anchors_map_right_to_left_under_reflection(self, kind, extra):
        """A reflection swaps handedness, so the team's right becomes the other side of
        the pitch in nominal coordinates. Expecting x-flip alone is the wrong invariant."""
        left = anchor_from_spec({"kind": kind, "flank": "left", **extra}).resolve(
            context(wing_overload_snapshot())
        )
        right_mirrored = anchor_from_spec({"kind": kind, "flank": "right", **extra}).resolve(
            context(mirrored(wing_overload_snapshot()))
        )
        assert np.allclose(xflip(left), right_mirrored, atol=3.0)


class TestSpecValidation:
    def test_unknown_kind_lists_the_known_ones(self):
        with pytest.raises(AnchorError, match="behind_line"):
            anchor_from_spec({"kind": "somewhere_good"})

    def test_unknown_parameter_is_rejected(self):
        with pytest.raises(AnchorError, match="unknown parameter"):
            anchor_from_spec({"kind": "behind_line", "yards": 5})

    def test_non_object_is_rejected(self):
        with pytest.raises(AnchorError, match="must be an object"):
            anchor_from_spec(["behind_line"])

    def test_nested_specs_round_trip(self):
        """to_spec must keep nested kinds — asdict() flattened them and silently broke
        the round trip that makes plays-as-data work."""
        spec = {
            "kind": "offset",
            "base": {"kind": "behind_line", "metres": 4.0, "flank": "right", "line_count": 2},
            "forward": 2.0,
            "lateral": 1.0,
        }
        anchor = anchor_from_spec(spec)
        assert anchor.to_spec()["base"]["kind"] == "behind_line"
        assert anchor_from_spec(anchor.to_spec()).to_spec() == anchor.to_spec()

    def test_describe_is_readable(self):
        assert "behind_line" in anchor_from_spec({"kind": "behind_line"}).describe()
