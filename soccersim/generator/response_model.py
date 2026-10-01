"""Response model R(state, play) (spec §10.5); implemented alongside the critic."""

from .critic import OUTCOME_EVENTS, ResponseModel

__all__ = ["OUTCOME_EVENTS", "ResponseModel"]
