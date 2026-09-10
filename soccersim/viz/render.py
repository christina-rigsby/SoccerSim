"""matplotlib debug renderer for a single game state (D-011).

The space layer's characteristic failure is subtly wrong geometry — a control field
that looks plausible in aggregate statistics while being mirrored, offset, or
momentum-blind. Numeric assertions on synthetic cases do not catch that; looking at it
does. This module exists for looking at it.

Static snapshots only. A time-stepping loop would force movement-physics decisions
before there is any scoring function to drive movement.
"""

from __future__ import annotations

import numpy as np

from ..domain.entities import Team
from ..domain.pitch import Pitch
from ..domain.state import GameState
from ..space.grid import PitchGrid
from ..space.passing_lanes import LaneAssessment, cover_shadow_polygon
from ..space.pitch_control import ControlField

HOME_COLOUR = "#1f6feb"
AWAY_COLOUR = "#d1242f"
LINE_COLOUR = "#3d4450"
BALL_COLOUR = "#111418"


def draw_pitch(ax, pitch: Pitch) -> None:
    """Draw pitch markings derived from ``pitch``."""
    import matplotlib.patches as patches

    hl, hw = pitch.half_length, pitch.half_width
    style = dict(color=LINE_COLOUR, linewidth=1.2, zorder=3)

    ax.plot([-hl, hl, hl, -hl, -hl], [-hw, -hw, hw, hw, -hw], **style)
    ax.plot([0, 0], [-hw, hw], **style)
    ax.add_patch(
        patches.Circle(
            (0, 0), pitch.centre_circle_radius, fill=False, **style
        )
    )
    ax.plot([0], [0], marker="o", markersize=2, color=LINE_COLOUR, zorder=3)

    for side in (-1, 1):
        # Penalty box, goal area, penalty spot, goal.
        for depth, box_width in (
            (pitch.penalty_box_depth, pitch.penalty_box_width),
            (pitch.goal_area_depth, pitch.goal_area_width),
        ):
            x_edge = side * (hl - depth)
            ax.plot(
                [side * hl, x_edge, x_edge, side * hl],
                [-box_width / 2, -box_width / 2, box_width / 2, box_width / 2],
                **style,
            )
        spot_x = side * (hl - pitch.penalty_spot_distance)
        ax.plot([spot_x], [0], marker="o", markersize=2, color=LINE_COLOUR, zorder=3)
        ax.plot(
            [side * hl, side * (hl + 2.0), side * (hl + 2.0), side * hl],
            [
                -pitch.goal_width / 2,
                -pitch.goal_width / 2,
                pitch.goal_width / 2,
                pitch.goal_width / 2,
            ],
            color=LINE_COLOUR,
            linewidth=2.0,
            zorder=3,
        )

    ax.set_xlim(-hl - 5, hl + 5)
    ax.set_ylim(-hw - 4, hw + 4)
    ax.set_aspect("equal")
    ax.axis("off")


def draw_players(ax, state: GameState, annotate: bool = True) -> None:
    """Draw both teams with velocity arrows; unavailable players are hollow."""
    for team_state, colour in ((state.home, HOME_COLOUR), (state.away, AWAY_COLOUR)):
        for player in team_state.players:
            x, y = player.position
            ax.scatter(
                [x],
                [y],
                s=170,
                facecolor=colour if player.available else "none",
                edgecolor="white" if player.available else colour,
                linewidth=1.4,
                zorder=6,
            )
            if annotate:
                ax.annotate(
                    str(player.player_id),
                    (x, y),
                    color="white" if player.available else colour,
                    fontsize=6.5,
                    ha="center",
                    va="center",
                    zorder=7,
                )
            if player.speed > 0.1:
                # Scaled so a top-speed sprint reads as a ~5 m arrow.
                ax.arrow(
                    x,
                    y,
                    player.velocity[0] * 0.65,
                    player.velocity[1] * 0.65,
                    head_width=1.1,
                    head_length=1.1,
                    fc=colour,
                    ec=colour,
                    alpha=0.75,
                    zorder=5,
                    length_includes_head=True,
                )

    bx, by = state.ball.position
    ax.scatter(
        [bx], [by], s=55, marker="o", facecolor=BALL_COLOUR, edgecolor="white",
        linewidth=1.0, zorder=8,
    )


def draw_field(
    ax,
    grid: PitchGrid,
    values: np.ndarray,
    cmap: str = "RdBu",
    vmin: float | None = None,
    vmax: float | None = None,
    alpha: float = 0.8,
    label: str | None = None,
):
    """Underlay a scalar field on the pitch, returning the image for a colourbar."""
    image = ax.imshow(
        values,
        origin="lower",
        extent=grid.extent,
        cmap=cmap,
        vmin=vmin,
        vmax=vmax,
        alpha=alpha,
        interpolation="bilinear",
        zorder=1,
    )
    if label:
        ax.set_title(label, fontsize=9, color=LINE_COLOUR)
    return image


def draw_lanes(ax, lanes: list[LaneAssessment]) -> None:
    """Draw passing lanes, solid green where open and dashed red where blocked."""
    for lane in lanes:
        colour = "#1a7f37" if lane.is_open else "#bf3989"
        ax.plot(
            [lane.origin[0], lane.target[0]],
            [lane.origin[1], lane.target[1]],
            color=colour,
            linewidth=1.6,
            linestyle="-" if lane.is_open else "--",
            alpha=0.9,
            zorder=4,
        )
        if not lane.is_open:
            ax.scatter(
                [lane.tightest_point[0]],
                [lane.tightest_point[1]],
                marker="x",
                s=40,
                color="#bf3989",
                zorder=5,
            )


def draw_cover_shadows(
    ax,
    state: GameState,
    team: Team,
    depth: float = 22.0,
    max_range: float = 35.0,
) -> None:
    """Draw the cover shadow of nearby opposing players, from the ball's position.

    Only defenders within ``max_range`` of the ball are drawn. A defender 60 m away
    casts a shadow that is geometrically real and tactically irrelevant, and drawing all
    eleven turns the pitch into noise.

    Shadows are drawn in a neutral charcoal, deliberately *not* the away colour: they
    are a property of the ball's line of sight, not a claim about who controls that
    space, and the control field is already saying the latter.
    """
    import matplotlib.patches as patches

    clip = patches.Rectangle(
        (-state.pitch.half_length, -state.pitch.half_width),
        state.pitch.length,
        state.pitch.width,
        transform=ax.transData,
    )

    ball = np.asarray(state.ball.position, dtype=float)
    for defender in state.opponents_of(team).available():
        if float(np.linalg.norm(defender.position - ball)) > max_range:
            continue
        polygon = cover_shadow_polygon(ball, defender.position, depth=depth)
        patch = patches.Polygon(
            polygon,
            closed=True,
            facecolor="#1b1f24",
            alpha=0.28,
            edgecolor="#1b1f24",
            linewidth=0.5,
            zorder=2,
        )
        ax.add_patch(patch)
        patch.set_clip_path(clip)


def draw_state(
    state: GameState,
    control: ControlField | None = None,
    threat: np.ndarray | None = None,
    threat_grid: PitchGrid | None = None,
    lanes: list[LaneAssessment] | None = None,
    shadows_for: Team | None = None,
    title: str | None = None,
    ax=None,
):
    """Render one game state with any combination of overlays.

    Only one scalar field can be underlaid at a time; if both ``control`` and ``threat``
    are given, control wins and threat is drawn as contours instead, since two
    overlapping heatmaps are unreadable.
    """
    import matplotlib.pyplot as plt

    if ax is None:
        _, ax = plt.subplots(figsize=(12.5, 8.2))

    draw_pitch(ax, state.pitch)

    if control is not None:
        image = draw_field(
            ax, control.grid, control.control, cmap="RdBu", vmin=0.0, vmax=1.0,
        )
        bar = ax.figure.colorbar(image, ax=ax, fraction=0.026, pad=0.02)
        bar.set_label(f"pitch control ({control.team.value})", fontsize=8)
        bar.ax.tick_params(labelsize=7)
        if threat is not None and threat_grid is not None:
            ax.contour(
                threat_grid.xs,
                threat_grid.ys,
                threat,
                levels=6,
                colors="#8250df",
                linewidths=0.7,
                alpha=0.7,
                zorder=2,
            )
    elif threat is not None and threat_grid is not None:
        image = draw_field(ax, threat_grid, threat, cmap="magma", alpha=0.85)
        bar = ax.figure.colorbar(image, ax=ax, fraction=0.026, pad=0.02)
        bar.set_label("expected threat (uncalibrated)", fontsize=8)
        bar.ax.tick_params(labelsize=7)

    if shadows_for is not None:
        draw_cover_shadows(ax, state, shadows_for)
    if lanes:
        draw_lanes(ax, lanes)

    draw_players(ax, state)

    if title:
        ax.set_title(title, fontsize=11, color="#111418", pad=12)

    return ax


def save_state(path: str, *args, **kwargs) -> str:
    """Render with :func:`draw_state` and write a PNG to ``path``."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    ax = draw_state(*args, **kwargs)
    ax.figure.tight_layout()
    ax.figure.savefig(path, dpi=140, facecolor="white")
    plt.close(ax.figure)
    return path
