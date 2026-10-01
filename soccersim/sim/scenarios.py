"""Team construction and scenario start states (spec §7.7).

Training uses short scenario episodes sampled from start-state distributions rather
than full matches. Every function takes an injected ``np.random.Generator``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..config import load_config
from ..controllers.shape import shape_targets
from ..schema.vocab import CAPABILITIES
from .ball import gain_control
from .restarts import award_restart, kickoff
from .state import DIRECTION, N_PER_TEAM, Ball, MatchState, team_players

SCENARIO_TYPES = (
    "build_up", "mid_progression", "final_third_attack", "transition_win", "transition_loss",
    "set_piece_corner", "random_open_play",
)


@dataclass
class Scenario:
    type: str = "random_open_play"
    attacking_team: int = 0              # the team that starts with (or wins) the ball
    home_formation: str = "4-3-3"
    away_formation: str = "4-3-3"
    minute: float = 30.0
    score: tuple[int, int] = (0, 0)
    randomise_capabilities: bool = True
    overrides: dict = field(default_factory=dict)   # {"caps": {player: {cap: v}}}

    def to_dict(self) -> dict:
        return {"type": self.type, "attacking_team": self.attacking_team, "home_formation": self.home_formation,
                "away_formation": self.away_formation, "minute": self.minute, "score": list(self.score)}


def sample_scenario(rng: np.random.Generator, types: tuple[str, ...] = SCENARIO_TYPES,
                    formations: tuple[str, ...] = ("4-3-3", "4-4-2", "3-5-2")) -> Scenario:
    return Scenario(
        type=str(rng.choice(list(types))),
        attacking_team=int(rng.integers(0, 2)),
        home_formation=str(rng.choice(list(formations))),
        away_formation=str(rng.choice(list(formations))),
        minute=float(rng.uniform(0, 90)),
        score=(int(rng.integers(0, 3)), int(rng.integers(0, 3))),
    )


def build_state(rng: np.random.Generator, scenario: Scenario, sim_cfg: dict,
                form_cfg: dict | None = None) -> MatchState:
    """Construct both squads in their formations (players at out-of-possession bases)."""
    form_cfg = form_cfg or load_config("formations")
    jitter = sim_cfg.get("randomisation", {}).get("capability_jitter", 0.0) if scenario.randomise_capabilities else 0.0
    slots, kinds, caps, base_out, base_in = [], [], [], [], []
    for form in (scenario.home_formation, scenario.away_formation):
        spec = form_cfg["formations"][form]
        if len(spec) != N_PER_TEAM:
            raise ValueError(f"formation {form} has {len(spec)} slots, need 11")
        for slot, s in spec.items():
            slots.append(slot)
            kinds.append(s["kind"])
            prof = form_cfg["profiles"][s["kind"]]
            c = np.array([prof[k] for k in CAPABILITIES], dtype=float)
            if jitter:
                c = c + rng.uniform(-jitter, jitter, size=len(c))
            caps.append(np.clip(c, 0.05, 1.0))
            base_out.append(s["out"])
            base_in.append(s["in"])
    caps_arr = np.array(caps)
    for p, capd in scenario.overrides.get("caps", {}).items():
        for k, v in capd.items():
            caps_arr[int(p), CAPABILITIES.index(k)] = v
    base_out_a = np.array(base_out, dtype=float)
    pos = base_out_a.copy()
    pos[N_PER_TEAM:] *= -1.0
    state = MatchState(
        pos=pos, vel=np.zeros((22, 2)), caps=caps_arr, stamina=np.ones(22), slots=slots, kinds=kinds,
        base_out=base_out_a, base_in=np.array(base_in, dtype=float),
        formations=(scenario.home_formation, scenario.away_formation), ball=Ball(),
        minute0=scenario.minute, score=list(scenario.score),
    )
    return state


def _place(state: MatchState, rng: np.random.Generator, attacking: int, ball_abs: np.ndarray, shape_cfg: dict,
           att_in_possession: bool = True, def_in_possession: bool = False, noise: float = 2.0,
           compress: float = 0.0) -> None:
    """Shape both teams around the ball. ``compress`` pulls outfielders toward the ball,
    for the congested areas transitions happen in."""
    for team, poss in ((attacking, att_in_possession), (1 - attacking, def_in_possession)):
        d = DIRECTION[team]
        tgt = shape_targets(state, team, poss, d * ball_abs, shape_cfg)
        if compress:
            outfield = np.array([state.kinds[i] != "GK" for i in team_players(team)])
            tgt[outfield] += compress * (d * ball_abs - tgt[outfield])
        idx = list(team_players(team))
        state.pos[idx] = d * (tgt + rng.normal(0.0, noise, size=tgt.shape))
    state.ball.pos = ball_abs.copy()


def _nearest(state: MatchState, team: int, point: np.ndarray, kinds: tuple[str, ...] | None = None) -> int:
    idx = [i for i in team_players(team) if kinds is None or state.kinds[i] in kinds]
    if not idx:
        idx = [i for i in team_players(team) if state.kinds[i] != "GK"]
    return idx[int(np.argmin(np.linalg.norm(state.pos[idx] - point, axis=1)))]


def setup_scenario(state: MatchState, scenario: Scenario, rng: np.random.Generator, sim_cfg: dict,
                   form_cfg: dict | None = None) -> None:
    """Place players and ball for ``scenario`` (mutates ``state``)."""
    form_cfg = form_cfg or load_config("formations")
    shape_cfg = form_cfg["shape"]
    a = scenario.attacking_team
    d = DIRECTION[a]
    typ = scenario.type
    side = float(rng.choice([-1.0, 1.0]))

    if typ == "build_up":
        ball_f = np.array([-47.0, 0.0])
        _place(state, rng, a, d * ball_f, shape_cfg, att_in_possession=False)
        state.last_control_team = a
        award_restart(state, "goal_kick", a, d * ball_f, sim_cfg)
    elif typ == "set_piece_corner":
        ball_f = np.array([52.5, side * 34.0])
        _place(state, rng, a, d * np.array([40.0, side * 10.0]), shape_cfg)
        state.last_control_team = a
        award_restart(state, "corner", a, d * ball_f, sim_cfg)
    elif typ == "kickoff":
        kickoff(state, a, sim_cfg)
    else:
        if typ == "mid_progression":
            ball_f = np.array([rng.uniform(-22, 5), side * rng.uniform(0, 26)])
            kinds = ("CB", "DM", "CM", "FB")
        elif typ == "final_third_attack":
            ball_f = np.array([rng.uniform(15, 36), side * rng.uniform(4, 30)])
            kinds = ("W", "AM", "CM", "ST", "FB")
        elif typ == "transition_win":
            ball_f = np.array([rng.uniform(-30, 10), side * rng.uniform(0, 25)])
            kinds = ("DM", "CM", "CB", "FB")
        elif typ == "transition_loss":
            # The *attacking* team loses the ball high up the pitch: the opponent wins it
            # deep in its own half. We express it from the winner's perspective.
            ball_f = np.array([rng.uniform(-38, -12), side * rng.uniform(0, 25)])
            kinds = ("CB", "DM", "FB", "CM")
        else:  # random_open_play
            ball_f = np.array([rng.uniform(-40, 40), rng.uniform(-30, 30)])
            kinds = None
        if typ in ("transition_win", "transition_loss"):
            # The winner was defending (out-of-possession shape), the loser attacking.
            _place(state, rng, a, d * ball_f, shape_cfg, att_in_possession=False, def_in_possession=True,
                   compress=0.3)
        else:
            _place(state, rng, a, d * ball_f, shape_cfg)
        holder = _nearest(state, a, d * ball_f, kinds)
        state.ball.pos = d * ball_f
        state.pos[holder] = d * ball_f
        if typ in ("transition_win", "transition_loss"):
            state.last_control_team = 1 - a
            gain_control(state, holder, sim_cfg, cause="tackle")
        else:
            state.last_control_team = None
            gain_control(state, holder, sim_cfg)
    state.pos[:, 0] = np.clip(state.pos[:, 0], -52.0, 52.0)
    state.pos[:, 1] = np.clip(state.pos[:, 1], -33.5, 33.5)
