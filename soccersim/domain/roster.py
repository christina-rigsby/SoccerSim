"""Roster loading — your squad's identity and ratings, from a data file.

A roster holds what is *constant about a player across a match*: their slot, physical
envelope, attributes, foot, and which play roles they have rehearsed. It deliberately
does **not** hold position or velocity, which belong to a snapshot. So loading a roster
yields :class:`RosterEntry` objects, and a snapshot combines an entry with a position to
make a :class:`~soccersim.domain.entities.PlayerState`.

Only *our own* players get a roster. An opponent's attributes cannot be authored — they
have to be inferred from observed play, which is Q-008 and part of M2 (D-021).

The file format is JSON, hand-edited, so the loader is strict on purpose: unknown keys,
unknown roles, duplicate ids and out-of-scale values all fail loudly with a message that
names the offending player. A silently-ignored typo in a squad file is a bug you find
three milestones later, when a role mysteriously has no takers.

Any key beginning with ``_`` is treated as a comment and ignored, since JSON has no
comment syntax and a hand-edited squad file wants annotations.
"""

from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Mapping

import numpy as np

from .attributes import Attributes, Foot
from .entities import CapabilityProfile, PlayerState, PositionalRole, Team
from .pitch import vec
from .roles import ROLE_CATALOGUE, archetype_capability

#: Where the home squad lives by default. Resolved relative to the repository rather
#: than the working directory, so fixtures load the same file wherever pytest is run.
REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_ROSTER_PATH = REPO_ROOT / "data" / "rosters" / "home.json"

_PLAYER_KEYS = frozenset(
    {
        "player_id",
        "shirt",
        "name",
        "positional_role",
        "foot",
        "attributes",
        "physical",
        "practised_roles",
    }
)
_PHYSICAL_KEYS = frozenset({"max_speed", "max_accel", "reaction_time"})
_ROSTER_KEYS = frozenset({"team", "name", "players"})


class RosterError(ValueError):
    """A roster file is malformed. The message always names where."""


def _strip_comments(value: Any) -> Any:
    """Drop ``_``-prefixed keys recursively."""
    if isinstance(value, dict):
        return {k: _strip_comments(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, list):
        return [_strip_comments(item) for item in value]
    return value


def _reject_unknown(where: str, given: Iterable[str], allowed: frozenset[str]) -> None:
    unknown = sorted(set(given) - allowed)
    if unknown:
        raise RosterError(
            f"{where}: unknown key(s) {', '.join(repr(k) for k in unknown)}. "
            f"Allowed: {', '.join(sorted(allowed))}. "
            "(Prefix a key with '_' to use it as a comment.)"
        )


@dataclass(frozen=True)
class RosterEntry:
    """One player's constant identity, independent of any moment in a match."""

    player_id: int
    positional_role: PositionalRole
    capability: CapabilityProfile
    attributes: Attributes
    foot: Foot = Foot.RIGHT
    name: str = ""
    shirt: int | None = None
    practised_roles: frozenset[str] = frozenset()

    def to_player_state(
        self,
        team: Team,
        position,
        velocity=None,
        stamina: float = 1.0,
        available: bool = True,
    ) -> PlayerState:
        """Combine this constant identity with a per-instant position."""
        return PlayerState(
            player_id=self.player_id,
            team=team,
            position=np.asarray(position, dtype=float),
            velocity=vec(0.0, 0.0) if velocity is None else np.asarray(velocity, dtype=float),
            positional_role=self.positional_role,
            capability=self.capability,
            stamina=stamina,
            available=available,
            name=self.name,
            shirt=self.shirt,
            attributes=self.attributes,
            foot=self.foot,
            practised_roles=self.practised_roles,
        )


@dataclass
class Roster:
    """A squad loaded from file."""

    team: Team
    name: str
    entries: dict[int, RosterEntry] = field(default_factory=dict)
    #: player_id -> attribute names that were absent and fell back to the 50 default.
    #: Surfaced rather than silently applied: a defaulted attribute looks like an
    #: authored one, and an unnoticed wall of 50s makes every role fit look mediocre
    #: for no visible reason.
    defaulted_attributes: dict[int, tuple[str, ...]] = field(default_factory=dict)
    source: pathlib.Path | None = None

    def __len__(self) -> int:
        return len(self.entries)

    def __iter__(self):
        return iter(self.entries.values())

    def entry(self, player_id: int) -> RosterEntry:
        try:
            return self.entries[player_id]
        except KeyError:
            raise KeyError(
                f"no player {player_id} in roster {self.name!r}; ids are "
                f"{sorted(self.entries)}"
            ) from None

    def by_slot(self, slot: PositionalRole) -> list[RosterEntry]:
        return [entry for entry in self if entry.positional_role is slot]

    def player_states(
        self,
        snapshot: Mapping[int, Mapping[str, Any]],
        team: Team | None = None,
    ) -> list[PlayerState]:
        """Build player states by merging this roster with per-instant values.

        ``snapshot`` maps player id to any of ``position``, ``velocity``, ``stamina``,
        ``available``. Every id must be in the roster; an unknown id is an error rather
        than an implicit extra player, since a typo'd id would otherwise produce a
        ghost.
        """
        states = []
        for player_id, values in snapshot.items():
            entry = self.entry(player_id)
            states.append(
                entry.to_player_state(
                    team or self.team,
                    position=values["position"],
                    velocity=values.get("velocity"),
                    stamina=values.get("stamina", 1.0),
                    available=values.get("available", True),
                )
            )
        return states

    def with_attributes(self, player_id: int, **changes: float) -> "Roster":
        """A copy with one player's attributes adjusted — for what-if tuning."""
        entry = self.entry(player_id)
        updated = replace(entry, attributes=replace(entry.attributes, **changes))
        entries = dict(self.entries)
        entries[player_id] = updated
        return Roster(self.team, self.name, entries, dict(self.defaulted_attributes), self.source)

    def summary(self) -> str:
        lines = [f"{self.name} ({self.team.value}) — {len(self)} players"]
        for entry in sorted(self, key=lambda e: (e.shirt or e.player_id)):
            practised = ", ".join(sorted(entry.practised_roles)) or "—"
            lines.append(
                f"  {entry.positional_role.value:<4} "
                f"#{entry.shirt or entry.player_id:<3}{entry.name:<18} "
                f"{entry.foot.value:<5} "
                f"{entry.capability.max_speed:.1f} m/s   practised: {practised}"
            )
        return "\n".join(lines)


def _parse_physical(
    where: str, raw: Mapping[str, Any] | None, slot: PositionalRole
) -> CapabilityProfile:
    """Physical profile, defaulting per-field to the slot's archetype."""
    base = archetype_capability(slot)
    if not raw:
        return base
    _reject_unknown(f"{where} physical", raw, _PHYSICAL_KEYS)
    values = {name: float(raw.get(name, getattr(base, name))) for name in _PHYSICAL_KEYS}
    for name, value in values.items():
        if value <= 0:
            raise RosterError(f"{where}: physical {name} is {value}; must be positive")
    return CapabilityProfile(**values)


def _parse_player(index: int, raw: Mapping[str, Any]) -> tuple[RosterEntry, tuple[str, ...]]:
    label = raw.get("name") or raw.get("shirt") or raw.get("player_id") or f"index {index}"
    where = f"player {label!r}"
    _reject_unknown(where, raw, _PLAYER_KEYS)

    if "player_id" not in raw:
        raise RosterError(f"{where}: missing required key 'player_id'")
    try:
        player_id = int(raw["player_id"])
    except (TypeError, ValueError):
        raise RosterError(f"{where}: player_id {raw['player_id']!r} is not an integer") from None

    slot_name = raw.get("positional_role")
    if slot_name is None:
        raise RosterError(f"{where}: missing required key 'positional_role'")
    try:
        slot = PositionalRole(slot_name)
    except ValueError:
        raise RosterError(
            f"{where}: unknown positional_role {slot_name!r}; valid slots are "
            f"{', '.join(r.value for r in PositionalRole if r is not PositionalRole.UNKNOWN)}"
        ) from None

    foot_name = raw.get("foot", "right")
    try:
        foot = Foot(foot_name)
    except ValueError:
        raise RosterError(
            f"{where}: unknown foot {foot_name!r}; valid values are "
            f"{', '.join(f.value for f in Foot)}"
        ) from None

    raw_attributes = raw.get("attributes") or {}
    if not isinstance(raw_attributes, Mapping):
        raise RosterError(f"{where}: 'attributes' must be an object, got {type(raw_attributes).__name__}")
    known = set(Attributes.names())
    unknown = sorted(set(raw_attributes) - known)
    if unknown:
        raise RosterError(
            f"{where}: unknown attribute(s) {', '.join(repr(k) for k in unknown)}. "
            f"Known: {', '.join(sorted(known))}."
        )
    defaulted = tuple(sorted(known - set(raw_attributes)))
    try:
        attributes = Attributes(**{k: float(v) for k, v in raw_attributes.items()})
    except ValueError as error:
        raise RosterError(f"{where}: {error}") from None

    practised = frozenset(raw.get("practised_roles") or ())
    unknown_roles = sorted(practised - set(ROLE_CATALOGUE))
    if unknown_roles:
        raise RosterError(
            f"{where}: unknown practised role(s) {', '.join(repr(k) for k in unknown_roles)}. "
            f"Catalogue: {', '.join(sorted(ROLE_CATALOGUE))}."
        )

    entry = RosterEntry(
        player_id=player_id,
        positional_role=slot,
        capability=_parse_physical(where, raw.get("physical"), slot),
        attributes=attributes,
        foot=foot,
        name=str(raw.get("name", "")),
        shirt=int(raw["shirt"]) if raw.get("shirt") is not None else None,
        practised_roles=practised,
    )
    return entry, defaulted


def parse_roster(data: Mapping[str, Any], source: pathlib.Path | None = None) -> Roster:
    """Validate and build a :class:`Roster` from already-decoded JSON."""
    data = _strip_comments(data)
    if not isinstance(data, Mapping):
        raise RosterError("roster must be a JSON object")
    _reject_unknown("roster", data, _ROSTER_KEYS)

    team_name = data.get("team", "home")
    try:
        team = Team(team_name)
    except ValueError:
        raise RosterError(
            f"roster: unknown team {team_name!r}; valid values are "
            f"{', '.join(t.value for t in Team)}"
        ) from None
    if team is not Team.HOME:
        raise RosterError(
            "roster: only the home team can have an authored roster. An opponent's "
            "attributes must be inferred from observed play (Q-008), not written down."
        )

    players = data.get("players")
    if not isinstance(players, list) or not players:
        raise RosterError("roster: 'players' must be a non-empty list")

    entries: dict[int, RosterEntry] = {}
    defaulted: dict[int, tuple[str, ...]] = {}
    for index, raw in enumerate(players):
        if not isinstance(raw, Mapping):
            raise RosterError(f"roster: players[{index}] must be an object")
        entry, missing = _parse_player(index, raw)
        if entry.player_id in entries:
            raise RosterError(
                f"roster: duplicate player_id {entry.player_id} "
                f"({entries[entry.player_id].name!r} and {entry.name!r})"
            )
        entries[entry.player_id] = entry
        if missing:
            defaulted[entry.player_id] = missing

    return Roster(
        team=team,
        name=str(data.get("name", "roster")),
        entries=entries,
        defaulted_attributes=defaulted,
        source=source,
    )


def load_roster(path: str | pathlib.Path = DEFAULT_ROSTER_PATH) -> Roster:
    """Load and validate a roster file."""
    path = pathlib.Path(path)
    if not path.exists():
        raise RosterError(
            f"no roster at {path}. Copy the template and fill it in, or pass an "
            "explicit path."
        )
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as error:
        raise RosterError(f"{path}: invalid JSON — {error}") from None
    return parse_roster(data, source=path)
