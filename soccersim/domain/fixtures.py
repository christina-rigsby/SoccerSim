"""Canonical game-state snapshots, shared by tests and the demo script.

Hand-authored rather than generated, so each one is a recognisable football situation
that a human can check a rendered pitch-control field against. Home always attacks
``+x`` and away ``-x`` (D-012).
"""

from __future__ import annotations

import functools

import numpy as np

from .entities import (
    BallPhase,
    BallState,
    GamePhase,
    PlayerState,
    PositionalRole,
    Team,
)
from .pitch import Pitch, vec
from .roles import archetype_capability
from .roster import DEFAULT_ROSTER_PATH, Roster, load_roster
from .state import GameState, TeamState


@functools.lru_cache(maxsize=1)
def home_roster(path=DEFAULT_ROSTER_PATH) -> Roster:
    """The home squad, loaded once and reused across fixtures."""
    return load_roster(path)


def _home_team(
    snapshot: list[tuple[int, tuple[float, float], tuple[float, float], float]],
) -> TeamState:
    """Merge the roster's constant identity with this snapshot's positions.

    The roster supplies slot, physical envelope, attributes, foot and practised roles;
    the snapshot supplies only what changes moment to moment. That split is the whole
    point of loading a roster rather than hand-authoring players (D-021).
    """
    roster = home_roster()
    players = [
        roster.entry(player_id).to_player_state(
            Team.HOME, position=vec(*position), velocity=vec(*velocity), stamina=stamina
        )
        for player_id, position, velocity, stamina in snapshot
    ]
    return TeamState(team=Team.HOME, players=players, attacking_direction=1)


def _away_team(
    entries: list[tuple[int, str, tuple[float, float], tuple[float, float], float]],
) -> TeamState:
    """Build the opposition, deliberately without attributes.

    An opponent's ratings cannot be authored — they have to be inferred from observed
    play, which is Q-008 and part of M2. Away players therefore carry ``attributes=None``
    and a positional archetype for their physical envelope. Any attempt to match one to
    a play role raises with an explanation rather than quietly using made-up numbers
    (D-021).
    """
    players = [
        PlayerState(
            player_id=player_id,
            team=Team.AWAY,
            position=vec(*position),
            velocity=vec(*velocity),
            positional_role=PositionalRole(role),
            capability=archetype_capability(PositionalRole(role)),
            stamina=stamina,
        )
        for player_id, role, position, velocity, stamina in entries
    ]
    return TeamState(team=Team.AWAY, players=players, attacking_direction=-1)


def kickoff_433_vs_442() -> GameState:
    """Settled shapes, no pressure: home 4-3-3 against away 4-4-2.

    The baseline sanity fixture — pitch control should look like two orderly blocks
    meeting near the halfway line.
    """
    home = _home_team(
        [
            (1, (-50.0, 0.0), (0.0, 0.0), 1.0),
            (2, (-35.0, -22.0), (0.0, 0.0), 1.0),
            (3, (-38.0, -8.0), (0.0, 0.0), 1.0),
            (4, (-38.0, 8.0), (0.0, 0.0), 1.0),
            (5, (-35.0, 22.0), (0.0, 0.0), 1.0),
            (6, (-22.0, 0.0), (0.0, 0.0), 1.0),
            (7, (-15.0, -12.0), (0.0, 0.0), 1.0),
            (8, (-15.0, 12.0), (0.0, 0.0), 1.0),
            (9, (-5.0, -26.0), (0.0, 0.0), 1.0),
            (10, (-1.0, 0.0), (0.0, 0.0), 1.0),
            (11, (-5.0, 26.0), (0.0, 0.0), 1.0),
        ],
    )
    away = _away_team(
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
    home = _home_team(
        [
            (1, (-40.0, 0.0), (0.0, 0.0), 1.0),
            (2, (-2.0, -20.0), (1.0, 0.0), 0.72),
            (3, (2.0, -6.0), (0.5, 0.0), 0.85),
            (4, (4.0, 6.0), (0.5, 0.0), 0.83),
            (5, (18.0, 30.0), (6.0, 1.0), 0.61),  # overlapping
            (6, (14.0, 2.0), (1.0, 0.0), 0.78),
            (7, (20.0, -10.0), (2.0, 0.0), 0.70),
            (8, (22.0, 12.0), (3.0, 1.0), 0.66),
            (9, (36.0, -18.0), (4.0, 1.0), 0.74),  # far-post runner
            (10, (38.0, 4.0), (2.0, -1.0), 0.69),
            (11, (30.0, 26.0), (1.0, 0.0), 0.64),  # on the ball
        ],
    )
    away = _away_team(
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
    home = _home_team(
        [
            (1, (-46.0, 0.0), (0.0, 0.0), 1.0),
            (2, (-24.0, -20.0), (2.0, 0.0), 0.80),
            (3, (-26.0, -7.0), (1.0, 0.0), 0.88),
            (4, (-26.0, 7.0), (1.0, 0.0), 0.86),
            (5, (-22.0, 20.0), (3.0, 0.0), 0.79),
            (6, (-8.0, 4.0), (2.0, 1.0), 0.82),  # won the ball
            (7, (-6.0, -12.0), (5.0, -1.0), 0.77),
            (8, (-10.0, 14.0), (4.0, 1.0), 0.75),
            (9, (2.0, -20.0), (7.0, -1.0), 0.81),
            (10, (14.0, -6.0), (7.0, -1.0), 0.84),  # running behind
            (11, (8.0, 22.0), (6.0, 1.0), 0.80),
        ],
    )
    away = _away_team(
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


def opponent_buildup_snapshot() -> GameState:
    """Away plays out from the back; home presses high. The only out-of-possession fixture.

    Added because the press plays could not be instantiated at all against the other
    three: ``opponent(which="carrier")`` correctly refuses to resolve while our own team
    has the ball, so a library with out-of-possession plays needs a fixture where the
    opponent has it.

    Set up as the moment §3's trigger press keys on — the ball has gone back to a
    centre-back in the build-up area, with home's front line close enough to engage.
    """
    home = _home_team(
        [
            (1, (-30.0, 0.0), (0.0, 0.0), 1.0),
            (2, (0.0, -22.0), (1.0, 0.0), 0.86),
            (3, (-4.0, -8.0), (1.0, 0.0), 0.90),
            (4, (-4.0, 8.0), (1.0, 0.0), 0.89),
            (5, (0.0, 22.0), (1.0, 0.0), 0.85),
            (6, (12.0, 0.0), (2.0, 0.0), 0.88),
            (7, (18.0, -10.0), (3.0, -1.0), 0.84),
            (8, (18.0, 10.0), (3.0, 1.0), 0.85),
            (9, (30.0, -16.0), (4.0, -1.0), 0.87),
            (10, (34.0, -2.0), (5.0, -1.0), 0.88),  # closing the carrier
            (11, (30.0, 16.0), (4.0, 1.0), 0.86),
        ]
    )
    away = _away_team(
        [
            (21, "GK", (49.0, 0.0), (0.0, 0.0), 1.0),
            (22, "RB", (36.0, -20.0), (0.0, 0.0), 0.88),
            (23, "RCB", (40.0, -7.0), (-1.0, 0.0), 0.90),  # on the ball
            (24, "LCB", (40.0, 7.0), (0.0, 0.0), 0.90),
            (25, "LB", (36.0, 20.0), (0.0, 0.0), 0.87),
            (26, "RM", (22.0, -22.0), (0.0, -1.0), 0.85),
            (27, "RCM", (26.0, -6.0), (-1.0, 0.0), 0.86),
            (28, "LCM", (26.0, 6.0), (-1.0, 0.0), 0.86),
            (29, "LM", (22.0, 22.0), (0.0, 1.0), 0.85),
            (30, "ST", (8.0, -6.0), (0.0, 0.0), 0.88),
            (31, "ST", (8.0, 6.0), (0.0, 0.0), 0.88),
        ]
    )
    return GameState(
        pitch=Pitch(),
        home=home,
        away=away,
        ball=BallState(
            position=vec(40.0, -7.0),
            carrier_id=23,
            phase=BallPhase.ON_GROUND,
        ),
        score=(1, 0),
        clock_seconds=35.0 * 60.0,
        phase=GamePhase.OPEN_PLAY,
        possession=Team.AWAY,
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
    "opponent_buildup": opponent_buildup_snapshot,
}
