"""The closed vocabularies of the play schema (spec §3–§4).

Everything a play file may name — zones, anchors, selectors, hints, capabilities,
event types, action types and their parameters — is enumerated here, so the validator,
the evaluator and the tokenizer all agree on one list.
"""

from __future__ import annotations

HINTS = ("GK", "CB_near", "CB_far", "FB_near", "FB_far", "DM", "CM", "AM", "W_near", "W_far", "ST")

CAPABILITIES = (
    "pace", "acceleration", "stamina", "passing", "vision", "crossing", "dribbling",
    "first_touch", "finishing", "aerial", "tackling", "positioning", "composure",
)

PHASES = ("in_possession", "out_of_possession", "transition_attack", "transition_defense", "set_piece")
#: Phases in which a role may start with the ball (spec §4.6).
POSSESSION_PHASES = ("in_possession", "transition_attack", "set_piece")
OBJECTIVES = (
    "retain_possession", "progress_ball", "create_chance", "score",
    "regain_possession", "delay", "protect_goal",
)
SOURCES = ("library", "generated", "promoted")
TEMPOS = ("slow", "medium", "fast")

# -- zones (§3.1) ---------------------------------------------------------------------

BANDS = {
    "own_third": (-52.5, -17.5),
    "mid_own": (-17.5, 0.0),
    "mid_opp": (0.0, 17.5),
    "final_third": (17.5, 52.5),
}
LANES = {
    "near_wing": (20.16, 34.0),
    "near_halfspace": (9.16, 20.16),
    "center": (-9.16, 9.16),
    "far_halfspace": (-20.16, -9.16),
    "far_wing": (-34.0, -20.16),
}
SPECIAL_ZONES = (
    "box", "own_box", "zone14", "cutback_zone", "near_post_area", "far_post_area", "own_box_edge",
)


def is_zone(zone: str) -> bool:
    """Whether ``zone`` is a valid zone id, including ``band.*`` / ``*.lane`` wildcards."""
    if not isinstance(zone, str):
        return False
    if zone in SPECIAL_ZONES:
        return True
    if "." not in zone:
        return False
    band, lane = zone.split(".", 1)
    if band == "*" and lane == "*":
        return True
    return (band == "*" or band in BANDS) and (lane == "*" or lane in LANES)


# -- anchors, lines, selectors (§3.2–3.5) ---------------------------------------------

LINES = ("opp_first_line", "opp_second_line", "opp_last_line", "our_first_line", "our_second_line", "our_last_line")
FIXED_ANCHORS = ("ball", "ball_holder", "goal", "own_goal", "near_post", "far_post", "penalty_spot", "byline_near")
SIMPLE_SELECTORS = ("ball_carrier", "nearest_to_ball", "nearest_receiver", "second_receiver", "most_dangerous")

# -- events (§4.5) --------------------------------------------------------------------

EVENT_TYPES = (
    "pass_completed", "pass_intercepted", "possession_won", "possession_lost", "shot_taken",
    "goal", "goal_conceded", "ball_out", "ball_out_them_last", "foul_won", "tackle_won",
    "goal_kick_ours", "goal_kick_theirs", "corner_ours", "throw_in_ours",
)

# -- action vocabulary (§4.4) ---------------------------------------------------------
# Each action type maps parameter name -> (kind, required). Kinds are checked by the
# validator: target, role, opp_selector, line, lane, number, bool, event, or an enum
# given as a tuple of allowed strings.

PASS_STYLES = ("ground", "driven", "lofted", "through")
CROSS_STYLES = ("whipped", "lofted", "driven_low")
SPEEDS = ("jog", "fast", "max")

ACTION_SPECS: dict[str, dict[str, tuple[object, bool]]] = {
    # on-ball
    "pass": {"to": ("target", True), "style": (PASS_STYLES, False), "one_touch": ("bool", False)},
    "cross": {"to": ("target", True), "style": (CROSS_STYLES, False)},
    "cutback": {"to": ("target", True)},
    "carry": {"to": ("target", True), "speed": (SPEEDS, False), "protect": ("bool", False)},
    "dribble": {"to": ("target", True), "beat": ("opp_selector", False)},
    "shoot": {"placement": (("auto", "near", "far"), False), "style": (("placed", "power"), False)},
    "hold_up": {"duration_s": ("number", True)},
    "clear": {"to": ("target", False)},
    "distribute": {"to": ("target", True), "style": (PASS_STYLES, False)},
    # off-ball
    "run_to": {"to": ("target", True), "speed": (SPEEDS, False), "arrive_with": ("role", False)},
    "overlap": {"around": ("role", True), "to": ("target", False), "speed": (SPEEDS, False)},
    "underlap": {"around": ("role", True), "to": ("target", False), "speed": (SPEEDS, False)},
    "third_man_run": {"to": ("target", True), "speed": (SPEEDS, False)},
    "spin_in_behind": {"line": ("line", True), "lane": ("lane", True), "depth": ("number", True)},
    "check_to_ball": {"distance": ("number", True), "duration_s": ("number", True)},
    "decoy_run": {"to": ("target", True), "speed": (SPEEDS, False)},
    "support": {
        "from": ("role", True),
        "angle": (("back_inside", "back_outside", "square", "forward"), True),
        "distance": ("number", True),
    },
    "hold_width": {"lane": ("lane", True)},
    "hold_position": {"to": ("target", True)},
    # defensive
    "press": {"target": ("target", True), "curve": (("force_outside", "force_inside", "none"), False),
              "intensity": ("number", False)},
    "cover": {"behind": ("role", True), "depth": ("number", False)},
    "mark": {"target": ("target", True), "tightness": ("number", False), "goal_side": ("bool", False)},
    "block_lane": {"from": ("opp_selector", True), "to": ("opp_selector", True)},
    "block_shot": {},
    "jockey": {"target": ("target", True)},
    "tackle": {"target": ("target", True)},
    "recover": {"to": ("target", False), "speed": (SPEEDS, False)},
    "compact_shift": {"line_height": ("number", True), "width": ("number", True), "ball_shift": ("number", False)},
    "hold_line": {"height": ("number", True), "step_up_on": ("event", False)},
    # keeper
    "set_position": {"mode": (("cover_line", "sweep"), True)},
}

ACTION_CATEGORY = {
    **{t: "on_ball" for t in ("pass", "cross", "cutback", "carry", "dribble", "shoot", "hold_up", "clear",
                              "distribute")},
    **{t: "off_ball" for t in ("run_to", "overlap", "underlap", "third_man_run", "spin_in_behind",
                               "check_to_ball", "decoy_run", "support", "hold_width", "hold_position")},
    **{t: "defensive" for t in ("press", "cover", "mark", "block_lane", "block_shot", "jockey", "tackle",
                                "recover", "compact_shift", "hold_line")},
    "set_position": "keeper",
}

#: Actions that release the ball (they complete on release).
RELEASING_ACTIONS = ("pass", "cross", "cutback", "shoot", "clear", "distribute")
#: Actions that need the actor to have the ball.
ON_BALL_ACTIONS = tuple(t for t, c in ACTION_CATEGORY.items() if c == "on_ball")

COMPARATORS = ("lt", "le", "gt", "ge", "eq")
PREDICATE_KEYS = (
    "possession", "has_ball", "ball_in_zone", "role_in_zone", "dist", "ahead_of", "pressure_on",
    "lane_open", "pc_at", "xg", "line_height", "count_in_zone", "goal_side_count", "teammates_near",
    "onside", "event", "ball_beyond_line", "ball_behind_line", "elapsed_s", "step_elapsed_s", "game",
)
