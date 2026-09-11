"""Loading and validating the play library.

Plays are JSON, like the roster, so a play authored by hand, copied from a coaching
source, or emitted by a miner are all the same kind of thing. The loader is strict for
the same reason the roster loader is: a silently-ignored typo in a play file is a bug you
find when a play mysteriously never fires.

Any key beginning with ``_`` is a comment and ignored, since JSON has none and these
files carry a lot of explanation.
"""

from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass, field
from typing import Iterator

from .play import Play, PlayError, play_from_spec

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_PLAY_DIR = REPO_ROOT / "data" / "plays"


@dataclass
class PlayLibrary:
    """Every loaded play, indexed by key."""

    plays: dict[str, Play] = field(default_factory=dict)
    source: pathlib.Path | None = None

    def __len__(self) -> int:
        return len(self.plays)

    def __iter__(self) -> Iterator[Play]:
        return iter(self.plays.values())

    def __contains__(self, key: object) -> bool:
        return key in self.plays

    def get(self, key: str) -> Play:
        try:
            return self.plays[key]
        except KeyError:
            raise KeyError(
                f"unknown play {key!r}; library holds {', '.join(sorted(self.plays))}"
            ) from None

    def by_objective(self, objective: str) -> list[Play]:
        return [play for play in self if play.objective == objective]

    def by_strategy(self, strategy: str) -> list[Play]:
        return [play for play in self if play.strategy == strategy]

    def in_possession(self, wanted: bool = True) -> list[Play]:
        return [play for play in self if play.requires_possession is wanted]

    def roles_used(self) -> set[str]:
        return {role for play in self for role in play.roles()}

    def summary(self) -> str:
        lines = [f"{len(self)} plays"]
        header = f"  {'key':<22}{'objective':<24}{'strategy':<26}{'roles':>6}{'depth':>7}{'width':>7}"
        lines.append(header)
        lines.append("  " + "-" * (len(header) - 2))
        for play in sorted(self, key=lambda p: (p.objective, p.strategy, p.key)):
            structure = play.structure()
            lines.append(
                f"  {play.key:<22}{play.objective:<24}{play.strategy:<26}"
                f"{structure['roles']:>6}{structure['chain_depth']:>7}"
                f"{structure['parallel_width']:>7}"
            )
        return "\n".join(lines)


def _strip_comments(value):
    if isinstance(value, dict):
        return {k: _strip_comments(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, list):
        return [_strip_comments(item) for item in value]
    return value


def load_play(path: str | pathlib.Path) -> Play:
    """Load one play file."""
    path = pathlib.Path(path)
    try:
        raw = json.loads(path.read_text())
    except FileNotFoundError:
        raise PlayError(f"no play file at {path}") from None
    except json.JSONDecodeError as error:
        raise PlayError(f"{path}: invalid JSON — {error}") from None
    try:
        return play_from_spec(_strip_comments(raw))
    except PlayError as error:
        raise PlayError(f"{path}: {error}") from None


def load_library(directory: str | pathlib.Path = DEFAULT_PLAY_DIR) -> PlayLibrary:
    """Load every ``*.json`` play in ``directory``.

    A duplicate key across two files is an error rather than a last-one-wins, since
    silently shadowing a play would make the library's behaviour depend on filesystem
    order.
    """
    directory = pathlib.Path(directory)
    if not directory.is_dir():
        raise PlayError(f"no play directory at {directory}")

    library = PlayLibrary(source=directory)
    for path in sorted(directory.glob("*.json")):
        play = load_play(path)
        if play.key in library.plays:
            raise PlayError(
                f"duplicate play key {play.key!r}: defined in both "
                f"{library.plays[play.key].source or '?'} and {path.name}"
            )
        library.plays[play.key] = play
    if not library.plays:
        raise PlayError(f"no play files found in {directory}")
    return library
