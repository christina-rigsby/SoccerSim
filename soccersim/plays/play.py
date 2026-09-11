"""The play type — a dependency graph of triggered steps, not a list of coordinates.

A play is a small program over the geometry layer. Each step names a *play role* (from
M0.5's catalogue, so it is filled by capability rather than by shirt number), an *action*
(from §3's vocabulary), an *anchor* saying where (resolved live, so it adapts to the
opponent's shape), and a *trigger* saying when (an event, not a clock time).

The steps form a **directed acyclic graph**, and that is not decoration. §5 defines
``chain_depth_penalty`` as computed "directly from the play's internal action-dependency
graph" — plays with long sequential chains are riskier than plays with parallel
independent actions, because each handoff is another chance for the opponent to break it.
A flat list could not express that, so the graph is the primary structure and the
longest path through it *is* the chain depth.

The same graph gives §5's ``single_ball`` hard constraint for free: two ball-touching
steps conflict exactly when neither is an ancestor of the other, since then nothing
orders them.

**No weights here.** Structural quantities — chain depth, parallel width, concurrency
conflicts — are computed; how they turn into penalties waits for Q-001 (D-022's cut line
applied again).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Iterable, Mapping

import numpy as np

from ..constraints.feasibility import Violation, check_waypoints
from ..constraints.roles import check_role_requirements
from ..domain.actions import get_action
from ..domain.entities import Team, Waypoint
from ..domain.roles import ROLE_CATALOGUE
from ..domain.state import GameState
from .anchors import Anchor, AnchorError, PlayContext, anchor_from_spec
from .triggers import Immediately, Trigger, TriggerError, trigger_from_spec

#: How close a player must get to a waypoint to have "arrived", when the action does not
#: define completion some other way.
DEFAULT_ARRIVAL_TOLERANCE = 2.5

#: Default seconds a step may stay active before the play gives up on it. Every step
#: needs one, or a play whose trigger never fires would hang forever — which is the
#: mechanism behind D-002's willingness to abort and reselect.
DEFAULT_TIMEOUT = 4.0


class PlayError(ValueError):
    """A play is structurally invalid."""


@dataclass(frozen=True)
class PlayStep:
    """One player's job within a play."""

    key: str
    role: str
    action: str
    anchor: Anchor | None = None
    #: When the step activates, once its dependencies are complete.
    trigger: Trigger = field(default_factory=Immediately)
    depends_on: tuple[str, ...] = ()
    timeout: float = DEFAULT_TIMEOUT
    #: Overrides the action's default completion test.
    completes_when: Trigger | None = None
    #: Abandon this step (and the play) when this fires — D-002 made concrete.
    abort_if: Trigger | None = None
    arrival_tolerance: float = DEFAULT_ARRIVAL_TOLERANCE
    note: str = ""

    def __post_init__(self) -> None:
        spec = get_action(self.action)
        if self.role not in ROLE_CATALOGUE:
            raise PlayError(
                f"step {self.key!r}: unknown play role {self.role!r}. Catalogue is "
                f"{', '.join(sorted(ROLE_CATALOGUE))}."
            )
        if spec.needs_anchor and self.anchor is None:
            raise PlayError(
                f"step {self.key!r}: action {self.action!r} needs an anchor "
                "(it is meaningless without a target)"
            )
        if not spec.needs_anchor and self.anchor is not None:
            raise PlayError(
                f"step {self.key!r}: action {self.action!r} takes no anchor, but one "
                "was given"
            )
        if self.timeout <= 0:
            raise PlayError(f"step {self.key!r}: timeout must be positive")
        # Trigger fields must be built objects, not raw specs. Without this a spec that
        # slipped through unconverted fails deep inside the executor with an
        # AttributeError, tens of frames after the mistake was made.
        for field_name in ("trigger", "completes_when", "abort_if"):
            value = getattr(self, field_name)
            if value is not None and not isinstance(value, Trigger):
                raise PlayError(
                    f"step {self.key!r}: {field_name} must be a Trigger, got "
                    f"{type(value).__name__}. Build it with "
                    f"soccersim.plays.triggers.trigger_from_spec()."
                )
        if self.anchor is not None and not isinstance(self.anchor, Anchor):
            raise PlayError(
                f"step {self.key!r}: anchor must be an Anchor, got "
                f"{type(self.anchor).__name__}. Build it with "
                "soccersim.plays.anchors.anchor_from_spec()."
            )
        object.__setattr__(self, "depends_on", tuple(self.depends_on))

    @property
    def action_spec(self):
        return get_action(self.action)

    @property
    def is_on_ball(self) -> bool:
        return self.action_spec.is_on_ball

    def describe(self) -> str:
        where = f" -> {self.anchor.describe()}" if self.anchor else ""
        deps = f" after {','.join(self.depends_on)}" if self.depends_on else ""
        return (
            f"{self.key}: {self.role} {self.action}{where}"
            f"  when {self.trigger.describe()}{deps}"
        )

    def to_spec(self) -> dict[str, Any]:
        spec: dict[str, Any] = {
            "key": self.key,
            "role": self.role,
            "action": self.action,
            "trigger": self.trigger.to_spec(),
        }
        if self.anchor is not None:
            spec["anchor"] = self.anchor.to_spec()
        if self.depends_on:
            spec["depends_on"] = list(self.depends_on)
        if self.timeout != DEFAULT_TIMEOUT:
            spec["timeout"] = self.timeout
        if self.completes_when is not None:
            spec["completes_when"] = self.completes_when.to_spec()
        if self.abort_if is not None:
            spec["abort_if"] = self.abort_if.to_spec()
        if self.arrival_tolerance != DEFAULT_ARRIVAL_TOLERANCE:
            spec["arrival_tolerance"] = self.arrival_tolerance
        if self.note:
            spec["note"] = self.note
        return spec


@dataclass(frozen=True)
class Play:
    """A named play: the objective and strategy it serves, and its step graph."""

    key: str
    label: str
    description: str
    objective: str
    strategy: str
    steps: tuple[PlayStep, ...]
    requires_possession: bool = True
    source: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "steps", tuple(self.steps))
        if not self.steps:
            raise PlayError(f"play {self.key!r} has no steps")

        seen: set[str] = set()
        for step in self.steps:
            if step.key in seen:
                raise PlayError(f"play {self.key!r}: duplicate step key {step.key!r}")
            seen.add(step.key)
        for step in self.steps:
            unknown = sorted(set(step.depends_on) - seen)
            if unknown:
                raise PlayError(
                    f"play {self.key!r}, step {step.key!r}: depends on unknown step(s) "
                    f"{', '.join(unknown)}"
                )
            if step.key in step.depends_on:
                raise PlayError(
                    f"play {self.key!r}, step {step.key!r}: depends on itself"
                )
        self.topological_order()  # raises on a cycle

    # -- lookups ---------------------------------------------------------------

    @property
    def step_map(self) -> dict[str, PlayStep]:
        return {step.key: step for step in self.steps}

    def step(self, key: str) -> PlayStep:
        try:
            return self.step_map[key]
        except KeyError:
            raise KeyError(
                f"play {self.key!r} has no step {key!r}; steps are "
                f"{', '.join(s.key for s in self.steps)}"
            ) from None

    def roles(self) -> tuple[str, ...]:
        """Distinct play roles this play requires, in first-appearance order."""
        return tuple(dict.fromkeys(step.role for step in self.steps))

    # -- graph structure -------------------------------------------------------

    def topological_order(self) -> tuple[str, ...]:
        """Step keys in dependency order, raising on a cycle."""
        remaining = {step.key: set(step.depends_on) for step in self.steps}
        order: list[str] = []
        while remaining:
            ready = sorted(key for key, deps in remaining.items() if not deps)
            if not ready:
                raise PlayError(
                    f"play {self.key!r}: dependency cycle among "
                    f"{', '.join(sorted(remaining))}"
                )
            for key in ready:
                order.append(key)
                del remaining[key]
            for deps in remaining.values():
                deps.difference_update(ready)
        return tuple(order)

    def depth_of(self, key: str) -> int:
        """Longest dependency path ending at ``key``, counting this step. Roots are 1."""
        depths: dict[str, int] = {}
        for step_key in self.topological_order():
            step = self.step(step_key)
            depths[step_key] = 1 + max(
                (depths[dep] for dep in step.depends_on), default=0
            )
        return depths[key]

    def chain_depth(self) -> int:
        """Longest sequential chain of dependent actions — §5's ``chain_depth_penalty``.

        The structural risk measure: each link is another handoff the opponent can
        disrupt. A three-pass counter has depth 3 or more; a play where five players move
        independently has depth 1 however many players it involves.
        """
        return max(self.depth_of(step.key) for step in self.steps)

    def parallel_width(self) -> int:
        """Most steps sharing a depth level — how much happens at once."""
        counts: dict[int, int] = {}
        for step in self.steps:
            depth = self.depth_of(step.key)
            counts[depth] = counts.get(depth, 0) + 1
        return max(counts.values())

    def terminal_steps(self) -> tuple[str, ...]:
        """Steps nothing depends on. The play is complete when all of these are."""
        depended_on = {dep for step in self.steps for dep in step.depends_on}
        return tuple(step.key for step in self.steps if step.key not in depended_on)

    def ancestors_of(self, key: str) -> frozenset[str]:
        collected: set[str] = set()
        frontier = list(self.step(key).depends_on)
        while frontier:
            current = frontier.pop()
            if current in collected:
                continue
            collected.add(current)
            frontier.extend(self.step(current).depends_on)
        return frozenset(collected)

    def concurrent_on_ball(self) -> list[tuple[str, str]]:
        """Pairs of ball-touching steps that nothing orders — §5's ``single_ball``.

        Two on-ball steps conflict exactly when neither is an ancestor of the other:
        without a dependency path between them the graph permits both to be active at
        once, and only one player can touch the ball at a given instant.
        """
        on_ball = [step.key for step in self.steps if step.is_on_ball]
        conflicts = []
        for index, first in enumerate(on_ball):
            for second in on_ball[index + 1:]:
                if second in self.ancestors_of(first) or first in self.ancestors_of(second):
                    continue
                conflicts.append((first, second))
        return conflicts

    def time_budget(self, key: str) -> float:
        """Seconds from play start by which ``key`` must be complete.

        The sum of timeouts along the longest path to this step. Used as the deadline
        when a step is turned into a :class:`~soccersim.domain.entities.Waypoint`, so
        the kinematic ``max_speed`` check asks the right question: can this player get
        there before the play would have given up on them?

        This is why chain depth and feasibility are linked — a step buried deep in a
        chain gets a later deadline but also depends on more that could go wrong.
        """
        budgets: dict[str, float] = {}
        for step_key in self.topological_order():
            step = self.step(step_key)
            start = max((budgets[dep] for dep in step.depends_on), default=0.0)
            budgets[step_key] = start + step.timeout
        return budgets[key]

    # -- structural report -----------------------------------------------------

    def structure(self) -> dict[str, Any]:
        """Weight-free structural metrics, for the ranking layer to consume later."""
        return {
            "steps": len(self.steps),
            "roles": len(self.roles()),
            "chain_depth": self.chain_depth(),
            "parallel_width": self.parallel_width(),
            "terminal_steps": len(self.terminal_steps()),
            "on_ball_steps": sum(1 for step in self.steps if step.is_on_ball),
            "single_ball_conflicts": len(self.concurrent_on_ball()),
            "total_time_budget": max(
                self.time_budget(step.key) for step in self.steps
            ),
        }

    def describe(self) -> str:
        lines = [
            f"{self.key} — {self.label}",
            f"  {self.objective} / {self.strategy}"
            f"{'  (needs possession)' if self.requires_possession else '  (out of possession)'}",
            f"  {self.description}",
            f"  roles: {', '.join(self.roles())}",
        ]
        structure = self.structure()
        lines.append(
            f"  chain depth {structure['chain_depth']}, "
            f"parallel width {structure['parallel_width']}, "
            f"budget {structure['total_time_budget']:.1f}s"
        )
        for key in self.topological_order():
            step = self.step(key)
            lines.append(f"    [{self.depth_of(key)}] {step.describe()}")
        return "\n".join(lines)

    def to_spec(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "description": self.description,
            "objective": self.objective,
            "strategy": self.strategy,
            "requires_possession": self.requires_possession,
            "source": self.source,
            "steps": [step.to_spec() for step in self.steps],
        }


# ---------------------------------------------------------------------------
# Instantiation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InstantiatedStep:
    """One step resolved against a concrete game state and role assignment."""

    step: PlayStep
    player_id: int
    target: np.ndarray | None
    waypoint: Waypoint | None
    #: Set when the anchor could not be resolved in this state — which is a real answer
    #: ("this play does not fit here"), not an error to suppress.
    error: str | None = None


@dataclass(frozen=True)
class InstantiatedPlay:
    """A play resolved to concrete waypoints for a specific moment and assignment."""

    play: Play
    assignment: dict[str, int]
    steps: tuple[InstantiatedStep, ...]
    context: PlayContext

    @property
    def waypoints(self) -> tuple[Waypoint, ...]:
        return tuple(s.waypoint for s in self.steps if s.waypoint is not None)

    @property
    def anchor_errors(self) -> dict[str, str]:
        return {s.step.key: s.error for s in self.steps if s.error}

    def receivers_of(self, step_key: str) -> tuple[int, ...]:
        """Player ids that receive the ball from ``step_key``.

        A ball-releasing step's receivers are the players whose steps depend on it, which
        is how the graph already encodes "this pass is to them".
        """
        releasing = self.play.step(step_key)
        if not releasing.action_spec.releases_ball:
            return ()
        receivers = {
            self.assignment[dependant.role]
            for dependant in self.play.steps
            if step_key in dependant.depends_on and dependant.role in self.assignment
        }
        return tuple(sorted(receivers))

    def violations(self) -> list[Violation]:
        """Every hard-constraint failure, reusing the M0 and M0.5 checks.

        Collects rather than short-circuits, matching ``check_waypoints`` — when
        authoring a play, all the problems at once beats one at a time.
        """
        state = self.context.state
        team_state = state.team_state(self.context.team)
        found: list[Violation] = []

        for key, message in self.anchor_errors.items():
            found.append(Violation("anchor_unresolvable", f"step {key!r}: {message}"))

        if self.play.requires_possession and state.possession is not self.context.team:
            found.append(
                Violation(
                    "possession_state",
                    f"play {self.play.key!r} requires possession, but it is with "
                    f"{state.possession.value if state.possession else 'nobody'}",
                )
            )
        elif not self.play.requires_possession and state.possession is self.context.team:
            found.append(
                Violation(
                    "possession_state",
                    f"play {self.play.key!r} is an out-of-possession play, but we have "
                    "the ball",
                )
            )

        for first, second in self.play.concurrent_on_ball():
            found.append(
                Violation(
                    "single_ball",
                    f"steps {first!r} and {second!r} both touch the ball and nothing in "
                    "the dependency graph orders them",
                )
            )

        found += check_role_requirements(team_state.players, self.play.roles())
        # Offside is deliberately *not* checked here. §5 defines it "at the moment of the
        # pass", and a run beyond the line is perfectly legal to make — you are only
        # offside if the ball is played to you while you are there. Checking it at
        # selection time would reject every counter-attack that involves running in
        # behind, which is most of them. Now that triggers exist (Q-009), the check
        # belongs where it is meaningful: the executor evaluates it when a ball-releasing
        # step actually fires. This resolves the approximation M0's `check_offside`
        # docstring flagged as pending.
        found += check_waypoints(state, team_state, self.waypoints)
        return found

    @property
    def is_feasible(self) -> bool:
        return not self.violations()

    def describe(self) -> str:
        lines = [f"{self.play.key} instantiated for {sorted(self.assignment.items())}"]
        for instantiated in self.steps:
            if instantiated.error:
                lines.append(f"  {instantiated.step.key}: UNRESOLVABLE — {instantiated.error}")
                continue
            target = (
                np.round(instantiated.target, 1).tolist()
                if instantiated.target is not None
                else "—"
            )
            lines.append(
                f"  {instantiated.step.key:<16} #{instantiated.player_id:<3} "
                f"{instantiated.step.action:<14} {target}"
                + (
                    f"  by {instantiated.waypoint.deadline:.1f}s"
                    if instantiated.waypoint
                    else ""
                )
            )
        violations = self.violations()
        lines.append(
            "  feasible" if not violations else f"  {len(violations)} violation(s):"
        )
        for violation in violations:
            lines.append(f"    {violation}")
        return "\n".join(lines)


def instantiate(
    play: Play,
    state: GameState,
    assignment: Mapping[str, int],
    team: Team = Team.HOME,
    grid_resolution: float = 2.0,
) -> InstantiatedPlay:
    """Resolve a play's anchors against one game state.

    Every role the play needs must be assigned. An anchor that cannot resolve is
    recorded as an error on that step rather than raised, so a single ill-fitting anchor
    yields a play reported as infeasible instead of an exception — which is what the
    hard-constraint pre-filter wants (D-005).
    """
    missing = sorted(set(play.roles()) - set(assignment))
    if missing:
        raise PlayError(
            f"play {play.key!r} needs roles {', '.join(missing)}, which are unassigned"
        )
    # One player cannot fill two roles in the same play — that is the whole reason §4
    # solves an assignment problem rather than picking each role independently.
    used: dict[int, str] = {}
    for role in play.roles():
        player_id = assignment[role]
        if player_id in used:
            raise PlayError(
                f"play {play.key!r}: player {player_id} is assigned to both "
                f"{used[player_id]!r} and {role!r}; roles must be filled by distinct "
                "players"
            )
        used[player_id] = role

    context = PlayContext(
        state=state,
        team=team,
        assignment=dict(assignment),
        grid_resolution=grid_resolution,
    )

    resolved: list[InstantiatedStep] = []
    for step in play.steps:
        player_id = assignment[step.role]
        target: np.ndarray | None = None
        waypoint: Waypoint | None = None
        error: str | None = None

        if step.anchor is not None:
            try:
                target = step.anchor.resolve(context)
            except (AnchorError, KeyError, ValueError) as failure:
                error = str(failure)

        # A waypoint is a "be here by then" requirement, so it only makes sense where
        # the anchor is a player destination. A releasing action's anchor is the ball's
        # destination and a sustained action has no arrival moment.
        if (
            target is not None
            and not step.action_spec.sustained
            and not step.action_spec.releases_ball
        ):
            waypoint = Waypoint(
                player_id=player_id,
                target=target,
                deadline=play.time_budget(step.key),
                action=step.action,
            )

        resolved.append(
            InstantiatedStep(
                step=step, player_id=player_id, target=target,
                waypoint=waypoint, error=error,
            )
        )

    return InstantiatedPlay(
        play=play, assignment=dict(assignment),
        steps=tuple(resolved), context=context,
    )


def play_from_spec(spec: Mapping[str, Any]) -> Play:
    """Build a play from its JSON form, validating strictly."""
    if not isinstance(spec, Mapping):
        raise PlayError(f"play must be an object, got {type(spec).__name__}")

    allowed = {
        "key", "label", "description", "objective", "strategy",
        "requires_possession", "source", "steps",
    }
    unknown = sorted(set(k for k in spec if not k.startswith("_")) - allowed)
    if unknown:
        raise PlayError(
            f"play {spec.get('key')!r}: unknown key(s) {', '.join(unknown)}. "
            f"Allowed: {', '.join(sorted(allowed))}."
        )
    for required in ("key", "label", "objective", "strategy", "steps"):
        if required not in spec:
            raise PlayError(f"play: missing required key {required!r}")

    raw_steps = spec["steps"]
    if not isinstance(raw_steps, list) or not raw_steps:
        raise PlayError(f"play {spec['key']!r}: 'steps' must be a non-empty list")

    step_allowed = {
        "key", "role", "action", "anchor", "trigger", "depends_on", "timeout",
        "completes_when", "abort_if", "arrival_tolerance", "note",
    }
    steps: list[PlayStep] = []
    for index, raw in enumerate(raw_steps):
        if not isinstance(raw, Mapping):
            raise PlayError(f"play {spec['key']!r}: steps[{index}] must be an object")
        raw = {k: v for k, v in raw.items() if not k.startswith("_")}
        unknown = sorted(set(raw) - step_allowed)
        if unknown:
            raise PlayError(
                f"play {spec['key']!r}, steps[{index}]: unknown key(s) "
                f"{', '.join(unknown)}. Allowed: {', '.join(sorted(step_allowed))}."
            )
        for required in ("key", "role", "action"):
            if required not in raw:
                raise PlayError(
                    f"play {spec['key']!r}, steps[{index}]: missing {required!r}"
                )
        kwargs: dict[str, Any] = {
            "key": raw["key"], "role": raw["role"], "action": raw["action"],
            "depends_on": tuple(raw.get("depends_on", ())),
            "note": raw.get("note", ""),
        }
        if "anchor" in raw:
            kwargs["anchor"] = anchor_from_spec(raw["anchor"])
        kwargs["trigger"] = (
            trigger_from_spec(raw["trigger"]) if "trigger" in raw else Immediately()
        )
        if "completes_when" in raw:
            kwargs["completes_when"] = trigger_from_spec(raw["completes_when"])
        if "abort_if" in raw:
            kwargs["abort_if"] = trigger_from_spec(raw["abort_if"])
        for numeric in ("timeout", "arrival_tolerance"):
            if numeric in raw:
                kwargs[numeric] = float(raw[numeric])
        try:
            steps.append(PlayStep(**kwargs))
        except (PlayError, AnchorError, TriggerError, KeyError) as failure:
            raise PlayError(f"play {spec['key']!r}, step {raw['key']!r}: {failure}") from None

    return Play(
        key=spec["key"], label=spec["label"],
        description=spec.get("description", ""),
        objective=spec["objective"], strategy=spec["strategy"],
        steps=tuple(steps),
        requires_possession=bool(spec.get("requires_possession", True)),
        source=spec.get("source", ""),
    )
