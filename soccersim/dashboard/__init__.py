"""Module 1 — the information dashboard.

Measurements (single-frame facts) live in :mod:`.measurements`; inference (accumulated
hypotheses) in :mod:`.marking` and :mod:`.pressing`; the stateful spine that makes
accumulation possible at all in :mod:`.observer`; and every inferred value is wrapped in
:class:`.estimate.Estimate` so it cannot be acted on before it has earned trust.
"""

from .dashboard import Dashboard, OpponentModel, TeamReport
from .estimate import Estimate
from .marking import MarkingScheme
from .measurements import BlockType, Pressure, TeamShape
from .observer import EventKind, MatchEvent, MatchObserver, PassDirection, Possession

__all__ = [
    "BlockType",
    "Dashboard",
    "Estimate",
    "EventKind",
    "MarkingScheme",
    "MatchEvent",
    "MatchObserver",
    "OpponentModel",
    "PassDirection",
    "Possession",
    "Pressure",
    "TeamReport",
    "TeamShape",
]
