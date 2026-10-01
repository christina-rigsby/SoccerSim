"""Pydantic models for the machine-executable play schema (spec §4).

The models enforce *shape* (field names, types, no unknown keys). Cross-references —
roles named by actions, zone ids, step graph — are checked by :mod:`.validate`, which
walks a parsed :class:`Play`. Predicates and targets stay as plain YAML structures
(dicts / strings) on the model and are checked by :mod:`.predicates` and
:mod:`.targets`, because they are recursive unions that read far better in YAML than as
a zoo of pydantic classes.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Predicate = Any  # validated structurally by schema.predicates


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Group(_Strict):
    count: int = Field(ge=1, le=11)


class Role(_Strict):
    id: str
    desc: str = ""
    hints: list[str] = Field(default_factory=list)
    requires: dict[str, float] = Field(default_factory=dict)
    prefers: dict[str, float] = Field(default_factory=dict)
    starts_with_ball: bool = False
    group: Group | None = None

    @property
    def slots(self) -> int:
        return self.group.count if self.group else 1


class Action(BaseModel):
    """An action: ``{role: R1, type: pass, ...params}`` or ``{actor: ..., type: ...}``.

    Parameters are kept as extra fields (``params``) and checked against
    :data:`~soccersim.schema.vocab.ACTION_SPECS` by the validator.
    """

    model_config = ConfigDict(extra="allow")

    type: str
    role: str | None = None
    actor: str | dict[str, str] | None = None

    @model_validator(mode="after")
    def _one_actor(self) -> Action:
        if (self.role is None) == (self.actor is None):
            raise ValueError(f"action {self.type!r} needs exactly one of 'role' or 'actor'")
        return self

    @property
    def params(self) -> dict[str, Any]:
        return dict(self.model_extra or {})


class ChooseOption(_Strict):
    when: Predicate
    actions: list[Action]


class Step(_Strict):
    id: str
    start_when: Predicate | None = None
    actions: list[Action] | None = None
    choose: list[ChooseOption] | None = None
    done_when: Predicate
    timeout_s: float | None = Field(default=None, gt=0)
    on_timeout: str = "abort"
    next: str | None = None


class SoftHints(_Strict):
    risk: float = Field(default=0.3, ge=0.0, le=1.0)
    chain_depth: int = Field(default=1, ge=0)
    tempo: Literal["slow", "medium", "fast"] = "medium"


class Play(_Strict):
    id: str
    name: str = ""
    version: int = 1
    phase: Literal["in_possession", "out_of_possession", "transition_attack", "transition_defense", "set_piece"]
    objective: Literal[
        "retain_possession", "progress_ball", "create_chance", "score", "regain_possession", "delay", "protect_goal"
    ]
    strategy: str = ""
    fallback: bool = False
    roles: list[Role]
    triggers: Predicate = "always"
    hard_constraints: list[Predicate] = Field(default_factory=list)
    steps: list[Step]
    success: Predicate
    abort: Predicate = Field(default_factory=lambda: {"any": []})
    max_duration_s: float = Field(gt=0)
    cooldown_s: float = Field(default=0.0, ge=0)
    soft_hints: SoftHints = Field(default_factory=SoftHints)
    source: Literal["library", "generated", "promoted"] = "library"
    # Provenance for generated / promoted plays (spec §11 promotion pipeline).
    provenance: dict[str, Any] | None = None

    # -- convenience ------------------------------------------------------------

    def role(self, role_id: str) -> Role:
        for r in self.roles:
            if r.id == role_id:
                return r
        raise KeyError(role_id)

    @property
    def role_ids(self) -> list[str]:
        return [r.id for r in self.roles]

    @property
    def ball_role(self) -> Role | None:
        for r in self.roles:
            if r.starts_with_ball:
                return r
        return None

    def step_index(self, step_id: str) -> int:
        for i, s in enumerate(self.steps):
            if s.id == step_id:
                return i
        raise KeyError(step_id)

    @property
    def n_slots(self) -> int:
        return sum(r.slots for r in self.roles)
