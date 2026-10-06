"""The visual interpolation of the fixed-step physics bodies (xlioncore::render_transform): the Soccer example opts in (the ball, the players and the referee carry a RenderTransform).

The physics keeps the pose before the last fixed step and the render draws a pose between it and the pose of the last step (game_time::m_FixedInterpolate); the Transform - what gameplay
reads - stays the pose of the last step. The game is paused to read a consistent snapshot: the Transform, the pose to draw and the pose before the step all belong to the same frame.
"""
import random
import time

SCENE = "5B388EFC2203EC6F"
BALL = "00005000"
MOVERS = [BALL, "00002001", "00002002", "00003001", "00003002", "00004000", "00002000", "00003000"]     # the ball, field players of both teams, the referee, the goalkeepers
EPS = 1e-4


def prop_text(level, entity: str, component: str, path: str) -> str:
    return level.ed.cmd(f"{level.name}\\GetProperty -Scene {SCENE} -Id {entity} -Component {component} -Path {path}")


def prop(level, entity: str, component: str, path: str) -> float:
    return float(prop_text(level, entity, component, path))


def snapshot(level, entity: str) -> dict:
    return {axis: dict( T=prop(level, entity, "Transform", f"Transform/Position/{axis}")
                      , R=prop(level, entity, "RenderTransform", f"RenderTransform/Position/{axis}")
                      , P=prop(level, entity, "RenderTransform", f"RenderTransform/PrevPosition/{axis}"))
            for axis in "XZ"}


def play_the_match(level):
    editor = level.ed
    assert editor.cmd("Play", allow_disk=True).startswith("Play requested")
    editor.wait_play_state("Playing", timeout=240)
    deadline = time.monotonic() + 30
    while level.ed.cmd(f"{level.name}\\GetProperty -Scene {SCENE} -Id 00001000 -Component SoccerMatch -Path SoccerMatch/Phase") != "Playing":
        assert time.monotonic() < deadline, "the match did not start"
        time.sleep(0.1)


def test_what_is_drawn_is_between_the_last_two_fixed_steps_and_gameplay_keeps_the_last_one(game_level):
    level, editor = game_level, game_level.ed
    play_the_match(level)
    try:
        between, moving = 0, 0
        rng = random.Random(7)
        for _ in range(10):
            editor.cmd("Pause")
            editor.wait_play_state("Paused")
            for entity in MOVERS:
                assert prop_text(level, entity, "RenderTransform", "RenderTransform/Active") == "true", f"{entity}: the physics has not blended it"
                for axis, v in snapshot(level, entity).items():
                    lo, hi = min(v["P"], v["T"]) - EPS, max(v["P"], v["T"]) + EPS
                    assert lo <= v["R"] <= hi, f"{entity} {axis}: drawn at {v['R']}, outside the last step {v['P']} .. {v['T']}"
                    if abs(v["T"] - v["P"]) > 1e-3:
                        moving += 1
                        if abs(v["R"] - v["T"]) > EPS and abs(v["R"] - v["P"]) > EPS:
                            between += 1
            editor.cmd("Play")
            editor.wait_play_state("Playing")
            time.sleep(0.1 + rng.random() * 0.2)
        assert moving > 0, "nothing moved: the test saw no motion to blend"
        assert between > 0, "no body was ever drawn between its two poses: it is drawn at the last step"
    finally:
        editor.cmd("Stop -Keep false")
        editor.wait_play_state("Stopped")


def test_a_body_that_is_moved_is_not_drawn_blended_across_the_jump(game_level):
    level, editor = game_level, game_level.ed
    play_the_match(level)
    try:
        for axis, value in (("Z", 0), ("X", 5)):
            editor.cmd(f"{level.name}\\SetProperty -Scene {SCENE} -Id {BALL} -Component Transform -Path Transform/Position/{axis} -After {value}")
        time.sleep(0.5)
        editor.cmd("Pause")
        editor.wait_play_state("Paused")
        v = snapshot(level, BALL)["X"]
        assert abs(v["T"] - 5) < 0.5 and abs(v["R"] - 5) < 0.5 and abs(v["P"] - 5) < 0.5, f"the ball is still blended from where it was: {v}"
    finally:
        editor.cmd("Stop -Keep false")
        editor.wait_play_state("Stopped")
