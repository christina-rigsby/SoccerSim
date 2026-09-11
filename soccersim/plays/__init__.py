"""Play building — module 2's play representation, without the ranking graph.

A play is a program over the geometry layer: named roles, actions from §3's vocabulary,
*anchors* that resolve to points against live state (so one play works against any
opponent shape), and *triggers* that fire on events rather than clock time. The steps form
a dependency DAG, which is what §5's ``chain_depth_penalty`` and ``single_ball`` read.

Everything is data — anchors, triggers and whole plays round-trip through JSON — so a
play authored by hand, taken from a coaching source, or generated later by module 3 are
all the same kind of object.

Deliberately contains no weights, costs or scoring: that is the graph layer, blocked on
Q-001.
"""

from .anchors import Anchor, AnchorError, PlayContext, anchor_from_spec
from .assignment import AssignmentResult, greedy_assignment
from .execution import ExecutionUpdate, PlayExecution, PlayState, StepState
from .library import PlayLibrary, load_library, load_play
from .play import (
    InstantiatedPlay,
    Play,
    PlayError,
    PlayStep,
    instantiate,
    play_from_spec,
)
from .triggers import Trigger, TriggerContext, TriggerError, trigger_from_spec

__all__ = [
    "Anchor", "AnchorError", "ExecutionUpdate", "InstantiatedPlay", "Play",
    "PlayContext", "PlayError", "PlayExecution", "PlayLibrary", "PlayState",
    "PlayStep", "StepState", "Trigger", "TriggerContext", "TriggerError",
    "AssignmentResult", "anchor_from_spec", "greedy_assignment", "instantiate",
    "load_library", "load_play",
    "play_from_spec", "trigger_from_spec",
]
