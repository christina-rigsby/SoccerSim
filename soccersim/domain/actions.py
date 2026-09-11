"""The action vocabulary from design doc §3.

Each action carries the small amount of metadata the play machinery actually needs:

``kind``
    On-ball, off-ball or defensive. On-ball actions are what §5's ``single_ball`` hard
    constraint governs — "only one player can execute a ball-touching action at a given
    instant" — so the classification has to be in the data rather than inferred from the
    name.

``needs_anchor``
    Whether the action is meaningless without a target. ``pass`` needs somewhere to go;
    ``hold_position`` does not.

``releases_ball``
    Whether the ball leaves the player. This does two jobs. It decides how the executor
    knows the step finished — a release completes when the carrier changes, whereas a run
    completes when the player arrives. And it settles what the step's *anchor means*: for
    a releasing action the anchor is where the **ball** goes, so the player needs no
    waypoint of their own (they already have the ball); for every other action the anchor
    is where the **player** goes. Conflating the two makes a crosser run to the near post
    and collide with the player attacking it.

``sustained``
    Whether the action is a continuous state rather than an event. ``mark_man`` and
    ``hold_position`` are held until the play ends; ``shoot`` happens once. Sustained
    actions never "complete" on their own, which the executor has to know or it waits
    forever.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ActionKind(Enum):
    ON_BALL = "on_ball"
    OFF_BALL = "off_ball"
    DEFENSIVE = "defensive"


@dataclass(frozen=True)
class ActionSpec:
    key: str
    kind: ActionKind
    description: str
    needs_anchor: bool = True
    releases_ball: bool = False
    sustained: bool = False

    @property
    def is_on_ball(self) -> bool:
        return self.kind is ActionKind.ON_BALL


def _spec(key, kind, description, **kwargs) -> ActionSpec:
    return ActionSpec(key=key, kind=kind, description=description, **kwargs)


ACTIONS: dict[str, ActionSpec] = {
    spec.key: spec
    for spec in (
        # -- on the ball (§3) ------------------------------------------------
        _spec("pass", ActionKind.ON_BALL, "Ground, lofted or through pass to a target",
              releases_ball=True),
        _spec("cross", ActionKind.ON_BALL, "Delivery into a target zone",
              releases_ball=True),
        _spec("shoot", ActionKind.ON_BALL, "Strike at goal", releases_ball=True),
        _spec("dribble", ActionKind.ON_BALL, "Carry the ball to a waypoint"),
        _spec("shield", ActionKind.ON_BALL, "Protect the ball from a pressure source",
              needs_anchor=False, sustained=True),
        _spec("clear", ActionKind.ON_BALL, "Remove the ball from danger",
              needs_anchor=False, releases_ball=True),
        _spec("header", ActionKind.ON_BALL, "Head the ball at a target",
              releases_ball=True),
        _spec("first_touch", ActionKind.ON_BALL, "Direct the first touch"),
        # -- off the ball (§3) -----------------------------------------------
        _spec("move_to", ActionKind.OFF_BALL, "Move to a waypoint"),
        _spec("run_behind", ActionKind.OFF_BALL, "Checking run beyond the defensive line"),
        _spec("overlap_run", ActionKind.OFF_BALL, "Run outside a teammate"),
        _spec("underlap_run", ActionKind.OFF_BALL, "Run inside a teammate"),
        _spec("decoy_run", ActionKind.OFF_BALL, "Run to draw a defender away"),
        _spec("hold_position", ActionKind.OFF_BALL, "Stay where you are",
              needs_anchor=False, sustained=True),
        _spec("create_width", ActionKind.OFF_BALL, "Stretch the pitch laterally"),
        _spec("create_depth", ActionKind.OFF_BALL, "Stretch the pitch vertically"),
        _spec("call_for_ball", ActionKind.OFF_BALL, "Signal availability",
              needs_anchor=False),
        # -- defensive (§3) --------------------------------------------------
        _spec("mark_man", ActionKind.DEFENSIVE, "Track a specific opponent",
              sustained=True),
        _spec("mark_zone", ActionKind.DEFENSIVE, "Hold a zone", sustained=True),
        _spec("press", ActionKind.DEFENSIVE, "Close down the ball carrier"),
        _spec("intercept_lane", ActionKind.DEFENSIVE, "Occupy a passing lane",
              sustained=True),
        _spec("tackle", ActionKind.DEFENSIVE, "Commit to winning the ball"),
        _spec("jockey", ActionKind.DEFENSIVE, "Delay without committing",
              sustained=True),
        _spec("cover_shadow", ActionKind.DEFENSIVE,
              "Body-position to block a lane while pressuring", sustained=True),
        _spec("track_run", ActionKind.DEFENSIVE, "Follow an opponent's run"),
        _spec("step_up", ActionKind.DEFENSIVE, "Push the line up for an offside trap",
              needs_anchor=False),
    )
}


def get_action(key: str) -> ActionSpec:
    try:
        return ACTIONS[key]
    except KeyError:
        raise KeyError(
            f"unknown action {key!r}; vocabulary is {', '.join(sorted(ACTIONS))}"
        ) from None


def on_ball_actions() -> frozenset[str]:
    """Actions that touch the ball, for §5's ``single_ball`` constraint."""
    return frozenset(key for key, spec in ACTIONS.items() if spec.is_on_ball)
