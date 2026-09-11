"""Scripted match sequences with known ground truth.

The dashboard's estimators infer things that are not directly observable, so the only
way to know whether they *work* is to feed them behaviour whose answer is known by
construction. Each scenario here plants a specific opponent behaviour — this away team
IS man-marking, this one presses on backpasses in the middle third — and carries a
:class:`ScenarioTruth` stating it. Tests then assert that the estimator recovers the
planted answer, and that it does *not* recover answers that were not planted (D-026).

The negative controls matter as much as the positive ones. An estimator that reports
"man-marking" for everything scores perfectly on a man-marking scenario.

**This is not the simulator.** It contains a deliberately crude position stepper
(constant-speed movement toward a target) purely to make positions change over time.
There is no ball physics, no play execution and no decision-making. The real
tick-based loop stays deferred until M1 gives it something to execute (D-011); mistaking
this for it would be a mistake.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .dashboard.marking import MarkingScheme
from .domain.entities import (
    BallPhase,
    BallState,
    GamePhase,
    PlayerState,
    PositionalRole,
    Team,
)
from .domain.fixtures import home_roster
from .domain.pitch import Pitch, vec
from .domain.roles import archetype_capability
from .domain.state import GameState, TeamState

DEFAULT_DT = 0.2  # 5 Hz

_AWAY_SLOTS: dict[int, str] = {
    21: "GK", 22: "RB", 23: "RCB", 24: "LCB", 25: "LB",
    26: "RM", 27: "RCM", 28: "LCM", 29: "LM", 30: "ST", 31: "ST",
}

#: Home players parked across the middle third, used by the pressing scenarios where
#: the interesting variable is the ball, not the runners.
_HOME_BASE: dict[int, tuple[float, float]] = {
    1: (-45.0, 0.0),
    2: (-12.0, -25.0), 3: (-20.0, -8.0), 4: (-20.0, 8.0), 5: (-12.0, 25.0),
    6: (0.0, 0.0), 7: (6.0, -12.0), 8: (6.0, 12.0),
    9: (14.0, -22.0), 10: (16.0, 0.0), 11: (14.0, 22.0),
}

#: Away in a mid block defending the ``+x`` goal.
_AWAY_BASE: dict[int, tuple[float, float]] = {
    21: (46.0, 0.0),
    22: (26.0, -18.0), 23: (28.0, -6.0), 24: (28.0, 6.0), 25: (26.0, 18.0),
    26: (14.0, -20.0), 27: (12.0, -6.0), 28: (12.0, 6.0), 29: (14.0, 20.0),
    30: (2.0, -5.0), 31: (2.0, 5.0),
}


@dataclass(frozen=True)
class ScenarioTruth:
    """What the opponent is actually doing, by construction."""

    marking_scheme: MarkingScheme | None = None
    #: defender id -> the attacker they are assigned to, where marking is man-to-man.
    marking_assignments: dict[int, int] = field(default_factory=dict)
    #: (pass direction, third) pairs that provoke a press.
    press_triggers: frozenset[tuple[str, str]] = frozenset()
    #: (direction, third) pairs deliberately *not* triggers — the negative control.
    press_non_triggers: frozenset[tuple[str, str]] = frozenset()
    presses: bool = False


@dataclass
class Scenario:
    name: str
    description: str
    truth: ScenarioTruth
    frames: list[GameState]

    def __len__(self) -> int:
        return len(self.frames)

    @property
    def duration(self) -> float:
        if not self.frames:
            return 0.0
        return self.frames[-1].clock_seconds - self.frames[0].clock_seconds


# ---------------------------------------------------------------------------
# State construction
# ---------------------------------------------------------------------------


def _make_state(
    clock: float,
    home: dict[int, tuple[np.ndarray, np.ndarray]],
    away: dict[int, tuple[np.ndarray, np.ndarray]],
    ball_position,
    carrier_id: int | None,
    possession: Team | None = Team.HOME,
    phase: GamePhase = GamePhase.OPEN_PLAY,
    pitch: Pitch | None = None,
) -> GameState:
    """Assemble one frame. Home identity comes from the roster, away from archetypes."""
    pitch = pitch or Pitch()
    roster = home_roster()
    home_players = [
        roster.entry(player_id).to_player_state(
            Team.HOME, position=position, velocity=velocity
        )
        for player_id, (position, velocity) in sorted(home.items())
    ]
    away_players = [
        PlayerState(
            player_id=player_id,
            team=Team.AWAY,
            position=np.asarray(position, dtype=float),
            velocity=np.asarray(velocity, dtype=float),
            positional_role=PositionalRole(_AWAY_SLOTS[player_id]),
            capability=archetype_capability(PositionalRole(_AWAY_SLOTS[player_id])),
        )
        for player_id, (position, velocity) in sorted(away.items())
    ]
    return GameState(
        pitch=pitch,
        home=TeamState(Team.HOME, home_players, 1),
        away=TeamState(Team.AWAY, away_players, -1),
        ball=BallState(
            position=np.asarray(ball_position, dtype=float),
            carrier_id=carrier_id,
            phase=BallPhase.ON_GROUND if carrier_id is not None else BallPhase.IN_FLIGHT,
        ),
        clock_seconds=clock,
        phase=phase,
        possession=possession,
    )


def _step_toward(position: np.ndarray, target: np.ndarray, max_step: float) -> np.ndarray:
    """Move at most ``max_step`` metres toward ``target``."""
    delta = np.asarray(target, dtype=float) - position
    distance = float(np.linalg.norm(delta))
    if distance <= max_step or distance < 1e-9:
        return np.asarray(target, dtype=float).copy()
    return position + delta / distance * max_step


def _advance(
    positions: dict[int, np.ndarray],
    targets: dict[int, np.ndarray],
    speeds: dict[int, float],
    dt: float,
) -> dict[int, tuple[np.ndarray, np.ndarray]]:
    """Step everyone toward their target and derive velocity from the displacement.

    Velocity is the realised displacement over ``dt``, not a declared value, so it can
    never disagree with the motion the positions describe — which matters because
    pitch control reads velocity while marking inference reads position deltas.
    """
    out: dict[int, tuple[np.ndarray, np.ndarray]] = {}
    for player_id, position in positions.items():
        target = targets.get(player_id, position)
        moved = _step_toward(position, target, speeds.get(player_id, 7.0) * dt)
        out[player_id] = (moved, (moved - position) / dt)
        positions[player_id] = moved
    return out


# ---------------------------------------------------------------------------
# Marking scenarios
# ---------------------------------------------------------------------------

#: Away defender -> the home attacker they shadow in the man-marking scenario.
MAN_ASSIGNMENTS: dict[int, int] = {
    22: 11, 23: 10, 24: 9, 25: 2, 26: 8, 27: 6, 28: 7, 29: 5,
}

#: Goal-side offset a marker holds relative to their man. Away defends ``+x``, so the
#: marker sits on the ``+x`` side.
_MARKER_OFFSET = vec(1.6, 0.0)


def _attacker_path(player_id: int, base: np.ndarray, clock: float) -> np.ndarray:
    """A distinctive looping run per attacker.

    Each player gets a different phase and amplitude so that, in the zonal scenario,
    attackers genuinely cross between zones — which is what makes "nearest attacker"
    unstable there and stable under man-marking.
    """
    phase = player_id * 0.7
    return base + vec(
        6.0 * np.sin(0.25 * clock + phase),
        9.0 * np.cos(0.19 * clock + phase),
    )


def man_marking_scenario(duration: float = 45.0, dt: float = DEFAULT_DT) -> Scenario:
    """Away defenders each shadow one specific home attacker.

    Markers track ``attacker position + goal-side offset``, so once converged their
    frame-to-frame displacement matches their man's almost exactly — high alignment and
    high target stability, which is what the estimator looks for.
    """
    home_positions = {pid: vec(*pos) for pid, pos in _HOME_BASE.items()}
    away_positions = {pid: vec(*pos) for pid, pos in _AWAY_BASE.items()}
    home_bases = {pid: vec(*pos) for pid, pos in _HOME_BASE.items()}
    away_bases = {pid: vec(*pos) for pid, pos in _AWAY_BASE.items()}
    speeds = {pid: 8.0 for pid in list(home_positions) + list(away_positions)}

    # Start markers already on their men. This scenario depicts a team that man-marks,
    # not one in the act of picking men up: a convergence transient would leave a large
    # early swing in each marker's separation, which is exactly the signal the estimator
    # reads to decide whether a separation is being *held*.
    for defender_id, attacker_id in MAN_ASSIGNMENTS.items():
        away_positions[defender_id] = (
            _attacker_path(attacker_id, home_bases[attacker_id], 0.0) + _MARKER_OFFSET
        )

    frames: list[GameState] = []
    clock = 0.0
    while clock <= duration:
        home_targets = {
            pid: _attacker_path(pid, home_bases[pid], clock)
            for pid in home_positions
            if pid != 1
        }
        away_targets: dict[int, np.ndarray] = {}
        for defender_id, attacker_id in MAN_ASSIGNMENTS.items():
            away_targets[defender_id] = (
                home_targets.get(attacker_id, home_positions[attacker_id]) + _MARKER_OFFSET
            )
        for pid in away_positions:
            away_targets.setdefault(pid, away_bases[pid])

        home = _advance(home_positions, home_targets, speeds, dt)
        away = _advance(away_positions, away_targets, speeds, dt)
        carrier = 10
        frames.append(
            _make_state(clock, home, away, home[carrier][0], carrier, Team.HOME)
        )
        clock += dt

    return Scenario(
        name="man_marking",
        description="Away man-marks: each defender shadows one attacker goal-side.",
        truth=ScenarioTruth(
            marking_scheme=MarkingScheme.MAN,
            marking_assignments=dict(MAN_ASSIGNMENTS),
        ),
        frames=frames,
    )


def zonal_scenario(duration: float = 45.0, dt: float = DEFAULT_DT) -> Scenario:
    """Away defenders hold fixed zones, shifting only laterally with the ball.

    The negative control for marking: attackers run the same looping paths as in the
    man-marking scenario, so any estimator that calls this man-marking is responding to
    attacker movement rather than to defender behaviour.
    """
    home_positions = {pid: vec(*pos) for pid, pos in _HOME_BASE.items()}
    away_positions = {pid: vec(*pos) for pid, pos in _AWAY_BASE.items()}
    home_bases = {pid: vec(*pos) for pid, pos in _HOME_BASE.items()}
    away_bases = {pid: vec(*pos) for pid, pos in _AWAY_BASE.items()}
    speeds = {pid: 8.0 for pid in home_positions} | {pid: 3.0 for pid in away_positions}

    frames: list[GameState] = []
    clock = 0.0
    while clock <= duration:
        home_targets = {
            pid: _attacker_path(pid, home_bases[pid], clock)
            for pid in home_positions
            if pid != 1
        }
        carrier_y = float(home_positions[10][1])
        # Zonal defenders slide with the ball but never leave their zone.
        away_targets = {
            pid: base + vec(0.0, 0.25 * carrier_y) for pid, base in away_bases.items()
        }

        home = _advance(home_positions, home_targets, speeds, dt)
        away = _advance(away_positions, away_targets, speeds, dt)
        carrier = 10
        frames.append(
            _make_state(clock, home, away, home[carrier][0], carrier, Team.HOME)
        )
        clock += dt

    return Scenario(
        name="zonal",
        description="Away defends zonally: fixed zones, sliding only with the ball.",
        truth=ScenarioTruth(marking_scheme=MarkingScheme.ZONAL),
        frames=frames,
    )


# ---------------------------------------------------------------------------
# Pressing scenarios
# ---------------------------------------------------------------------------

#: (passer, receiver, provokes a press). Every pass starts in the middle third; the
#: backpasses are pressed and the forward passes are not, so the estimator has to learn
#: a conditional rate rather than a count.
_PRESS_SCRIPT: list[tuple[int, int, bool]] = [
    (10, 6, True),    # back
    (6, 10, False),   # forward
    (10, 8, True),    # back
    (8, 11, False),   # forward
    (11, 5, True),    # back
    (5, 11, False),   # forward
    (11, 8, True),    # back
    (8, 10, False),   # forward
    (10, 7, True),    # back
    (7, 9, False),    # forward
    (9, 2, True),     # back
    (2, 9, False),    # forward
    (9, 7, True),     # back
    (7, 10, False),   # forward
    (10, 6, True),    # back
]

_FLIGHT = 1.0       # seconds the ball is in the air
_HOLD = 5.0         # seconds the receiver keeps it before the next pass
_PRESS_DELAY = 0.4  # how soon after receipt the press begins


def _pressing_scenario(
    script: list[tuple[int, int, bool]],
    presses: bool,
    name: str,
    description: str,
    truth: ScenarioTruth,
    dt: float = DEFAULT_DT,
) -> Scenario:
    for (_, receiver), (next_passer, _) in zip(
        [(a, b) for a, b, _ in script], [(a, b) for a, b, _ in script[1:]]
    ):
        if receiver != next_passer:
            raise ValueError(
                f"pass script does not chain: #{receiver} received but #{next_passer} "
                "passes next. The ball would teleport, and the observer would record a "
                "pass from the wrong origin while an earlier press is still live."
            )

    home_positions = {pid: vec(*pos) for pid, pos in _HOME_BASE.items()}
    away_positions = {pid: vec(*pos) for pid, pos in _AWAY_BASE.items()}
    away_bases = {pid: vec(*pos) for pid, pos in _AWAY_BASE.items()}
    speeds = {pid: 8.0 for pid in home_positions} | {pid: 7.5 for pid in away_positions}

    frames: list[GameState] = []
    clock = 0.0
    carrier: int | None = script[0][0]

    for passer, receiver, pressed in script:
        segment_end = clock + _FLIGHT + _HOLD
        pass_at = clock + _FLIGHT
        while clock < segment_end:
            in_flight = clock < pass_at
            carrier = None if in_flight else receiver
            if in_flight:
                progress = (clock - (pass_at - _FLIGHT)) / _FLIGHT
                ball = (1 - progress) * home_positions[passer] + progress * home_positions[
                    receiver
                ]
            else:
                ball = home_positions[receiver]

            away_targets = dict(away_bases)
            chasing = presses and pressed and clock >= pass_at + _PRESS_DELAY
            if chasing:
                # The three nearest outfielders collapse on the carrier.
                order = sorted(
                    (pid for pid in away_positions if pid != 21),
                    key=lambda pid: float(np.linalg.norm(away_positions[pid] - ball)),
                )
                for pid in order[:3]:
                    away_targets[pid] = np.asarray(ball, dtype=float)

            home = {pid: (pos.copy(), vec(0.0, 0.0)) for pid, pos in home_positions.items()}
            away = _advance(away_positions, away_targets, speeds, dt)
            frames.append(_make_state(clock, home, away, ball, carrier, Team.HOME))
            clock += dt

    return Scenario(name=name, description=description, truth=truth, frames=frames)


def backpass_press_scenario(dt: float = DEFAULT_DT) -> Scenario:
    """Away presses after backpasses in the middle third, but not after forward ones."""
    return _pressing_scenario(
        _PRESS_SCRIPT,
        presses=True,
        name="backpass_press",
        description=(
            "Away presses on backpasses in the middle third and ignores forward passes "
            "from the same zone."
        ),
        truth=ScenarioTruth(
            press_triggers=frozenset({("back", "middle")}),
            press_non_triggers=frozenset({("forward", "middle")}),
            presses=True,
        ),
        dt=dt,
    )


def passive_block_scenario(dt: float = DEFAULT_DT) -> Scenario:
    """Away holds its block and never presses — the pressing negative control.

    Identical pass script to :func:`backpass_press_scenario`, so an estimator that
    reports a backpass trigger here is keying on pass frequency rather than on any
    pressing behaviour.
    """
    return _pressing_scenario(
        _PRESS_SCRIPT,
        presses=False,
        name="passive_block",
        description="Away holds a mid block and never closes down. No triggers exist.",
        truth=ScenarioTruth(press_triggers=frozenset(), presses=False),
        dt=dt,
    )


ALL_SCENARIOS = {
    "man_marking": man_marking_scenario,
    "zonal": zonal_scenario,
    "backpass_press": backpass_press_scenario,
    "passive_block": passive_block_scenario,
}
