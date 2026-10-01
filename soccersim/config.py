"""Config loading (spec §2: everything config-driven, YAML in ``configs/``).

Configs are plain nested dicts. :func:`load_config` returns a deep copy so callers may
mutate their copy (for domain randomisation or tests) without affecting anyone else.
"""

from __future__ import annotations

import copy
import hashlib
import json
from functools import cache
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO_ROOT / "configs"
PLAYS_DIR = REPO_ROOT / "plays"


@cache
def _read(path: str) -> dict[str, Any]:
    with open(path) as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"config {path} must be a mapping")
    return data


def load_config(name: str, config_dir: Path | None = None) -> dict[str, Any]:
    """Load ``configs/<name>.yaml`` as a fresh deep copy."""
    base = Path(config_dir) if config_dir else CONFIG_DIR
    path = base / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"no config named {name!r} at {path}")
    return copy.deepcopy(_read(str(path)))


def deep_update(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``override`` into ``base`` (in place) and return ``base``."""
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            deep_update(base[key], value)
        else:
            base[key] = copy.deepcopy(value)
    return base


def config_hash(cfg: dict[str, Any]) -> str:
    """Stable short hash of a config, logged as provenance (spec §13)."""
    blob = json.dumps(cfg, sort_keys=True, default=str).encode()
    return hashlib.sha1(blob).hexdigest()[:12]
