"""Canonical game-state snapshots, shared by tests and the demo script.

Hand-authored rather than generated, so each one is a recognisable football situation
that a human can check a rendered pitch-control field against. Home always attacks
``+x`` and away ``-x`` (D-012).
"""

from __future__ import annotations

import numpy as np

from .entities import (
    BallPhase,
    BallState,
    CapabilityProfile,
    GamePhase,
    PlayerState,
    Team,
)
from .pitch import Pitch, vec
from .state import GameState, TeamState

# Rough positional archetypes. Wide players are quicker; centre-backs accelerate less.
QUICK = CapabilityProfile(max_speed=8.6, max_accel=7.0)
AVERAGE = CapabilityProfile(max_speed=7.8, max_accel=6.5)
STRONG = CapabilityProfile(max_speed=7.2, max_accel=5.8)
KEEPER = CapabilityProfile(max_speed=6.8, max_accel=5.5, reaction_time=0.25)

_PROFILES = {
    "GK": KEEPER,
    "CB": STRONG,
    "LCB": STRONG,
    "RCB": STRONG,
    "LB": QUICK,
    "RB": QUICK,
    "LW": QUICK,
    "RW": QUICK,
    "LM": QUICK,
    "RM": QUICK,
}


def _make_team(
    team: Team,
    direction: int,
    entries: list[tuple[int, str, tuple[float, float], tuple[float, float], float]],
) -> TeamState:
    players = [
        PlayerState(
            player_id=pid,
            team=team,
            position=vec(*pos),
            velocity=vec(*vel),
            role=role,
            capability=_PROFILES.get(role, AVERAGE),
            stamina=stamina,
        )
        for pid, role, pos, vel, stamina in entries
    ]
    return TeamState(team=team, players=players, attacking_direction=direction)


def kickoff_433_vs_442() -> GameState:
    """Settled shapes, no pressure: home 4-3-3 against away 4-4-2.

    The baseline sanity fixture — pitch control should look like two orderly blocks
    meeting near the halfway line.
    """
    home = _make_team(
        Team.HOME,
        1,
        [
            (1, "GK", (-50.0, 0.0), (0.0, 0.0), 1.0),
            (2, "LB", (-35.0, -22.0), (0.0, 0.0), 1.0),
            (3, "LCB", (-38.0, -8.0), (0.0, 0.0), 1.0),
            (4, "RCB", (-38.0, 8.0), (0.0, 0.0), 1.0),
            (5, "RB", (-35.0, 22.0), (0.0, 0.0), 1.0),
            (6, "CDM", (-22.0, 0.0), (0.0, 0.0), 1.0),
            (7, "LCM", (-15.0, -12.0), (0.0, 0.0), 1.0),
            (8, "RCM", (-15.0, 12.0), (0.0, 0.0), 1.0),
            (9, "LW", (-5.0, -26.0), (0.0, 0.0), 1.0),
            (10, "ST", (-1.0, 0.0), (0.0, 0.0), 1.0),
            (11, "RW", (-5.0, 26.0), (0.0, 0.0), 1.0),
        ],
    )
    away = _make_team(
        Team.AWAY,
        -1,
        [
            (21, "GK", (50.0, 0.0), (0.0, 0.0), 1.0),
            (22, "RB", (38.0, -20.0), (0.0, 0.0), 1.0),
            (23, "RCB", (40.0, -7.0), (0.0, 0.0), 1.0),
            (24, "LCB", (40.0, 7.0), (0.0, 0.0), 1.0),
            (25, "LB", (38.0, 20.0), (0.0, 0.0), 1.0),
            (26, "RM", (22.0, -24.0), (0.0, 0.0), 1.0),
            (27, "RCM", (20.0, -8.0), (0.0, 0.0), 1.0),
            (28, "LCM", (20.0, 8.0), (0.0, 0.0), 1.0),
            (29, "LM", (22.0, 24.0), (0.0, 0.0), 1.0),
            (30, "ST", (5.0, -6.0), (0.0, 0.0), 1.0),
            (31, "ST", (5.0, 6.0), (0.0, 0.0), 1.0),
        ],
    )
    return GameState(
        pitch=Pitch(),
        home=home,
        away=away,
        ball=BallState(position=vec(0.0, 0.0), phase=BallPhase.ON_GROUND, carrier_id=10),
        phase=GamePhase.KICKOFF,
        possession=Team.HOME,
    )


def wing_overload_snapshot() -> GameState:
    """Home attacking down the right; away's block has shifted across to cover it.

    Set up so the interesting geometry is visible: home has a local overload on the
    right (winger, overlapping full-back, near-side midfielder), while away's shift
    leaves the far side underloaded — which is the situation the "switch-and-cross" play
    from design doc §3 exists to punish. The far-post runner is deliberately placed just
    inside the offside line.
    """
    home = _make_team(
        Team.HOME,
        1,
        [
            (1, "GK", (-40.0, 0.0), (0.0, 0.0), 1.0),
            (2, "LB", (-2.0, -20.0), (1.0, 0.0), 0.72),
            (3, "LCB", (2.0, -6.0), (0.5, 0.0), 0.85),
            (4, "RCB", (4.0, 6.0), (0.5, 0.0), 0.83),
            (5, "RB", (18.0, 30.0), (6.0, 1.0), 0.61),  # overlapping
            (6, "CDM", (14.0, 2.0), (1.0, 0.0), 0.78),
            (7, "LCM", (20.0, -10.0), (2.0, 0.0), 0.70),
            (8, "RCM", (22.0, 12.0), (3.0, 1.0), 0.66),
            (9, "LW", (36.0, -18.0), (4.0, 1.0), 0.74),  # far-post runner
            (10, "ST", (38.0, 4.0), (2.0, -1.0), 0.69),
            (11, "RW", (30.0, 26.0), (1.0, 0.0), 0.64),  # on the ball
        ],
    )
    away = _make_team(
        Team.AWAY,
        -1,
        [
            (21, "GK", (50.0, 0.0), (0.0, 0.0), 1.0),
            (22, "RB", (42.0, -16.0), (0.0, 1.0), 0.70),
            (23, "RCB", (44.0, -2.0), (0.0, 2.0), 0.74),
            (24, "LCB", (44.0, 10.0), (0.0, 1.0), 0.72),
            (25, "LB", (44.0, 22.0), (-1.0, 1.0), 0.63),
            (26, "RM", (28.0, -14.0), (0.0, 3.0), 0.66),
            (27, "RCM", (26.0, 0.0), (0.0, 3.0), 0.68),
            (28, "LCM", (28.0, 12.0), (1.0, 2.0), 0.65),
            (29, "LM", (30.0, 24.0), (2.0, 1.0), 0.58),  # pressing the winger
            (30, "ST", (12.0, 6.0), (-2.0, 0.0), 0.71),
            (31, "ST", (14.0, -6.0), (-2.0, 0.0), 0.73),
        ],
    )
    return GameState(
        pitch=Pitch(),
        home=home,
        away=away,
        ball=BallState(
            position=vec(30.0, 26.0),
            velocity=vec(1.0, 0.0),
            carrier_id=11,
            phase=BallPhase.ON_GROUND,
        ),
        score=(0, 1),
        clock_seconds=62.0 * 60.0,
        phase=GamePhase.OPEN_PLAY,
        possession=Team.HOME,
    )


def counter_attack_snapshot() -> GameState:
    """Home has just won the ball in midfield with away committed forward.

    Away's front three are stranded in home's half and their back line is high and
    strung out — the transition disorganisation that design doc §3's counter-attack
    strategies target. Home's striker is running behind the line at speed.
    """
    home = _make_team(
        Team.HOME,
        1,
        [
            (1, "GK", (-46.0, 0.0), (0.0, 0.0), 1.0),
            (2, "LB", (-24.0, -20.0), (2.0, 0.0), 0.80),
            (3, "LCB", (-26.0, -7.0), (1.0, 0.0), 0.88),
            (4, "RCB", (-26.0, 7.0), (1.0, 0.0), 0.86),
            (5, "RB", (-22.0, 20.0), (3.0, 0.0), 0.79),
            (6, "CDM", (-8.0, 4.0), (2.0, 1.0), 0.82),  # won the ball
            (7, "LCM", (-6.0, -12.0), (5.0, -1.0), 0.77),
            (8, "RCM", (-10.0, 14.0), (4.0, 1.0), 0.75),
            (9, "LW", (2.0, -20.0), (7.0, -1.0), 0.81),
            (10, "ST", (14.0, -6.0), (7.0, -1.0), 0.84),  # running behind
            (11, "RW", (8.0, 22.0), (6.0, 1.0), 0.80),
        ],
    )
    away = _make_team(
        Team.AWAY,
        -1,
        [
            (21, "GK", (50.0, 0.0), (0.0, 0.0), 1.0),
            (22, "RB", (10.0, -24.0), (3.0, -1.0), 0.62),
            (23, "RCB", (16.0, -14.0), (4.0, 0.0), 0.64),
            (24, "LCB", (18.0, 2.0), (4.0, 0.0), 0.66),
            (25, "LB", (22.0, 14.0), (3.0, 1.0), 0.60),
            (26, "RM", (-14.0, -18.0), (3.0, 0.0), 0.58),
            (27, "RCM", (-8.0, -2.0), (2.0, 0.0), 0.61),
            (28, "LCM", (-12.0, 10.0), (3.0, 0.0), 0.59),
            (29, "LM", (-20.0, 16.0), (2.0, 0.0), 0.55),
            (30, "ST", (-26.0, 0.0), (1.0, 0.0), 0.57),
            (31, "ST", (-20.0, -10.0), (2.0, 0.0), 0.56),
        ],
    )
    return GameState(
        pitch=Pitch(),
        home=home,
        away=away,
        ball=BallState(
            position=vec(-8.0, 4.0),
            velocity=vec(2.0, 1.0),
            carrier_id=6,
            phase=BallPhase.CONTESTED,
        ),
        score=(1, 1),
        clock_seconds=78.0 * 60.0,
        phase=GamePhase.TRANSITION,
        possession=Team.HOME,
    )


def mirrored(state: GameState) -> GameState:
    """The same situation with both teams' attacking directions flipped in ``x``.

    Used to check that geometry code is direction-agnostic (Q-011): any quantity
    expressed relative to ``attacking_direction`` should be unchanged by this transform.
    """

    def flip_team(team_state: TeamState) -> TeamState:
        flipped = [
            p.moved_to(
                np.array([-p.position[0], p.position[1]]),
                np.array([-p.velocity[0], p.velocity[1]]),
            )
            for p in team_state.players
        ]
        return TeamState(
            team=team_state.team,
            players=flipped,
            attacking_direction=-team_state.attacking_direction,
        )

    ball = state.ball
    return GameState(
        pitch=state.pitch,
        home=flip_team(state.home),
        away=flip_team(state.away),
        ball=BallState(
            position=np.array([-ball.position[0], ball.position[1]]),
            velocity=np.array([-ball.velocity[0], ball.velocity[1]]),
            height=ball.height,
            carrier_id=ball.carrier_id,
            phase=ball.phase,
        ),
        score=state.score,
        clock_seconds=state.clock_seconds,
        phase=state.phase,
        possession=state.possession,
    )


ALL_FIXTURES = {
    "kickoff": kickoff_433_vs_442,
    "wing_overload": wing_overload_snapshot,
    "counter_attack": counter_attack_snapshot,
}
