"""Replay viewer (spec §13): pitch, players, ball, each team's active play, role labels and
targets, exported as a GIF / PNG strip (matplotlib) or a self-contained interactive HTML
page (:mod:`.replay_html`).

Frames are the 10 Hz tracking dicts recorded by :class:`~soccersim.sim.env.MatchEnv`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from .render import AWAY_COLOUR, HOME_COLOUR, draw_pitch

TEAM_COLOURS = (HOME_COLOUR, AWAY_COLOUR)
GENERATED_COLOUR = "#b8860b"


def _pitch():
    from ..domain.pitch import Pitch

    return Pitch()


def draw_frame(ax, frame: dict[str, Any], show_targets: bool = True, title: str | None = None) -> None:
    ax.clear()
    draw_pitch(ax, _pitch())
    pos = np.asarray(frame["p"])
    plays = frame["plays"]
    for tm in (0, 1):
        col = TEAM_COLOURS[tm]
        idx = range(tm * 11, tm * 11 + 11)
        info = plays.get(tm) or plays.get(str(tm))
        roles = (info or {}).get("roles", {})
        acts = plays.get(f"acts{tm}", {})
        for i in idx:
            x, y = pos[i]
            ax.scatter([x], [y], s=150, color=col, edgecolor="white", linewidth=1.2, zorder=6)
            role = roles.get(i, roles.get(str(i)))
            if role:
                ax.annotate(role, (x, y + 2.2), color=col, fontsize=6.5, ha="center", zorder=8, weight="bold")
            act = acts.get(i, acts.get(str(i)))
            if show_targets and act and act[0] not in ("hold", "shape"):
                ax.plot([x, act[1]], [y, act[2]], color=col, lw=0.8, alpha=0.6, ls="--", zorder=4)
                ax.scatter([act[1]], [act[2]], s=12, marker="x", color=col, zorder=4)
    bx, by = frame["b"]
    ax.scatter([bx], [by], s=60 if frame.get("bh") == "air" else 40, color="white", edgecolor="black", zorder=9)
    if frame.get("fl"):
        _, tx, ty = frame["fl"]
        ax.plot([bx, tx], [by, ty], color="black", lw=0.6, alpha=0.5, zorder=3)
    lines = []
    for tm, name in ((0, "Home"), (1, "Away")):
        info = plays.get(tm) or plays.get(str(tm))
        if info:
            tag = " [generated]" if info.get("source") != "library" else ""
            lines.append(f"{name}: {info['id']} ({info['step']}){tag}")
        else:
            lines.append(f"{name}: —")
    head = title or f"t = {frame['t']:.1f}s   score {frame['s'][0]}–{frame['s'][1]}"
    ax.set_title(head + "\n" + "   |   ".join(lines), fontsize=8)


def save_strip(frames: list[dict], path: str | Path, every: int = 10, cols: int = 3, max_panels: int = 12) -> Path:
    """A grid of snapshots — the quickest way to eyeball an episode."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    picks = frames[::every][:max_panels]
    rows = int(np.ceil(len(picks) / cols))
    fig, axes = plt.subplots(rows, cols, figsize=(6.2 * cols, 4.4 * rows))
    axes = np.atleast_1d(axes).ravel()
    for ax, fr in zip(axes, picks, strict=False):
        draw_frame(ax, fr)
    for ax in axes[len(picks):]:
        ax.axis("off")
    fig.tight_layout()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=80)
    plt.close(fig)
    return path


def save_gif(frames: list[dict], path: str | Path, step: int = 2, fps: int = 10) -> Path:
    """Animated GIF (every ``step``-th 10 Hz frame)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.animation import FuncAnimation, PillowWriter

    fig, ax = plt.subplots(figsize=(8, 5.6))
    sel = frames[::step]
    anim = FuncAnimation(fig, lambda k: draw_frame(ax, sel[k]), frames=len(sel), interval=1000 / fps)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    anim.save(str(path), writer=PillowWriter(fps=fps))
    plt.close(fig)
    return path
