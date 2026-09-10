"""Renderer smoke tests.

The renderer's real verification is a human looking at the PNG (D-011) — these tests
only guarantee that every overlay combination still draws, so a refactor cannot silently
break the tool that the visual check depends on.
"""

import matplotlib
import pytest

matplotlib.use("Agg")

from soccersim.domain.entities import Team  # noqa: E402
from soccersim.domain.fixtures import ALL_FIXTURES, wing_overload_snapshot  # noqa: E402
from soccersim.domain.pitch import Pitch  # noqa: E402
from soccersim.space.grid import PitchGrid  # noqa: E402
from soccersim.space.passing_lanes import open_lanes  # noqa: E402
from soccersim.space.pitch_control import control_field  # noqa: E402
from soccersim.space.xt import AnalyticThreatSurface  # noqa: E402
from soccersim.viz.render import save_state  # noqa: E402

GRID = PitchGrid(Pitch(), 6.0)  # coarse — these tests are about drawing, not accuracy


@pytest.mark.parametrize("name", sorted(ALL_FIXTURES))
def test_every_fixture_renders_with_all_overlays(name, tmp_path):
    state = ALL_FIXTURES[name]()
    lanes = [
        assessment
        for _, assessment in open_lanes(state, state.ball.position, Team.HOME)
    ]
    path = save_state(
        str(tmp_path / f"{name}.png"),
        state,
        control=control_field(state, Team.HOME, GRID),
        threat=AnalyticThreatSurface(state.pitch).field(GRID, 1),
        threat_grid=GRID,
        lanes=lanes,
        shadows_for=Team.HOME,
        title=name,
    )
    assert (tmp_path / f"{name}.png").stat().st_size > 0
    assert path.endswith(".png")


def test_renders_with_no_overlays(tmp_path):
    save_state(str(tmp_path / "bare.png"), wing_overload_snapshot())
    assert (tmp_path / "bare.png").stat().st_size > 0


def test_renders_threat_alone(tmp_path):
    state = wing_overload_snapshot()
    save_state(
        str(tmp_path / "threat.png"),
        state,
        threat=AnalyticThreatSurface(state.pitch).field(GRID, 1),
        threat_grid=GRID,
    )
    assert (tmp_path / "threat.png").stat().st_size > 0


def test_renders_an_unavailable_player(tmp_path):
    """Sent-off and injured players draw hollow rather than being skipped."""
    state = wing_overload_snapshot()
    state.home.players[3].available = False
    save_state(str(tmp_path / "reduced.png"), state, control=control_field(state, Team.HOME, GRID))
    assert (tmp_path / "reduced.png").stat().st_size > 0
