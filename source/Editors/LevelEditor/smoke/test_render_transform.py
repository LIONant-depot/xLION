"""The visual interpolation of the fixed-step physics bodies (xlioncore::render_transform): the Soccer example opts in (the ball, the players and the referee carry a RenderTransform).

The physics keeps the pose before the last fixed step; the render draws a pose between it and the Transform (what gameplay reads, never changed by this) by the game's
m_FixedInterpolate. A body further than the snap distance from its previous pose is drawn where it is. The game is paused to read a consistent snapshot: the Transform, the previous pose
and the interpolate all belong to the same frame.
"""
import random
import time

SCENE = "5B388EFC2203EC6F"
BALL = "00005000"
MOVERS = [BALL, "00002001", "00002002", "00003001", "00003002", "00004000", "00002000", "00003000"]     # the ball, field players of both teams, the referee, the goalkeepers
EPS = 1e-4


def prop(level, entity: str, component: str, path: str) -> float:
    return float(level.ed.cmd(f"{level.name}\\GetProperty -Scene {SCENE} -Id {entity} -Component {component} -Path {path}"))


def snapshot(level, entity: str) -> dict:
    """Per axis: the Transform (T) and the pose before the last step (P)."""
    pose = {axis: dict(T=prop(level, entity, "Transform", f"Transform/Position/{axis}")
                     , P=prop(level, entity, "RenderTransform", f"RenderTransform/PrevPosition/{axis}"))
            for axis in "XZ"}
    return pose


def fixed_interpolate(level) -> float:
    reply = level.ed.cmd(f"{level.name}\\GetTimeScale")
    return float(next(l for l in reply.splitlines() if l.startswith("fixed interpolate:")).split(":")[1])


def play_the_match(level):
    editor = level.ed
    assert editor.cmd("Play", allow_disk=True).startswith("Play requested")
    editor.wait_play_state("Playing", timeout=240)
    deadline = time.monotonic() + 30
    while level.ed.cmd(f"{level.name}\\GetProperty -Scene {SCENE} -Id 00001000 -Component SoccerMatch -Path SoccerMatch/Phase") != "Playing":
        assert time.monotonic() < deadline, "the match did not start"
        time.sleep(0.1)


def test_the_physics_keeps_the_pose_before_the_last_step_and_the_game_says_how_far_the_frame_is(game_level):
    level, editor = game_level, game_level.ed
    play_the_match(level)
    try:
        between, moving = 0, 0
        rng = random.Random(7)
        for _ in range(10):
            editor.cmd("Pause")
            editor.wait_play_state("Paused")
            alpha = fixed_interpolate(level)
            assert 0.0 <= alpha <= 1.0, f"the frame is not between two steps: {alpha}"
            for entity in MOVERS:
                v = snapshot(level, entity)
                step = max(abs(v[axis]["T"] - v[axis]["P"]) for axis in "XZ")
                assert step < 1.0, f"{entity}: the previous pose is {step} m from the pose of the last step (one fixed step is a few centimeters)"
                if step > 1e-3:
                    moving += 1
                    if 0.02 < alpha < 0.98:
                        between += 1
            editor.cmd("Play")
            editor.wait_play_state("Playing")
            time.sleep(0.1 + rng.random() * 0.2)
        assert moving > 0, "nothing moved: the test saw no motion to blend"
        assert between > 0, "the frame was never between two steps: everything is drawn at the last step"
    finally:
        editor.cmd("Stop -Keep false")
        editor.wait_play_state("Stopped")


def test_a_teleported_body_has_its_previous_pose_where_it_is_now(game_level):
    level, editor = game_level, game_level.ed
    play_the_match(level)
    try:
        for axis, value in (("Z", 0), ("X", 5)):
            editor.cmd(f"{level.name}\\SetProperty -Scene {SCENE} -Id {BALL} -Component Transform -Path Transform/Position/{axis} -After {value}")
        time.sleep(0.5)
        editor.cmd("Pause")
        editor.wait_play_state("Paused")
        v = snapshot(level, BALL)["X"]
        assert abs(v["T"] - 5) < 0.5 and abs(v["P"] - 5) < 0.5, f"the ball would be blended from where it was: {v}"
    finally:
        editor.cmd("Stop -Keep false")
        editor.wait_play_state("Stopped")
