"""Loading plays from ``plays/**/*.yaml`` (one play per file, spec §4)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ..config import PLAYS_DIR
from .models import Play
from .validate import PlayValidationError, parse_play


def load_play_file(path: str | Path) -> Play:
    path = Path(path)
    with open(path) as fh:
        data = yaml.safe_load(fh)
    return parse_play(data, source=str(path))


def load_library(
    root: str | Path | None = None,
    include: tuple[str, ...] = ("offensive", "defensive"),
) -> dict[str, Play]:
    """Load every play under ``root/<include>/``. Ids must be unique."""
    base = Path(root) if root else PLAYS_DIR
    plays: dict[str, Play] = {}
    for sub in include:
        for path in sorted((base / sub).glob("*.yaml")):
            play = load_play_file(path)
            if play.id in plays:
                raise PlayValidationError(play.id, ["duplicate play id in library"], str(path))
            plays[play.id] = play
    return plays


def play_to_dict(play: Play) -> dict[str, Any]:
    """Serialise a play back to a YAML-ready mapping (actions keep their params inline)."""
    data = play.model_dump(mode="json", exclude_none=True)
    # Defaults that add noise without information.
    if not data.get("fallback"):
        data.pop("fallback", None)
    return data


def play_to_yaml(play: Play) -> str:
    return yaml.safe_dump(play_to_dict(play), sort_keys=False, default_flow_style=None, width=110)
