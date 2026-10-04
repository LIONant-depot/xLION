"""The referee of the Soccer example walks along the touchline he is on and goes where the ball goes in x, never in z: the ball is always across from him.

The real game, played: the referee's position is read while the match runs.
"""
import time

SCENE = "5B388EFC2203EC6F"
REFEREE, BALL = "00004000", "00005000"


def position(level, entity: str, axis: str) -> float:
    return float(level.ed.cmd(f"{level.name}\\GetProperty -Scene {SCENE} -Id {entity} -Component Transform -Path Transform/Position/{axis}"))


def test_the_referee_follows_the_ball_along_his_touchline(game_level):
    editor = game_level.ed
    assert editor.cmd("Play", allow_disk=True).startswith("Play requested")
    editor.wait_play_state("Playing", timeout=240)
    try:
        deadline = time.monotonic() + 15.0                   # he starts inside the pitch and first walks out to his line
        while abs(abs(position(game_level, REFEREE, "Z")) - 6.0) > 0.2 and time.monotonic() < deadline:
            time.sleep(0.25)
        xs, zs, near = [], [], 0
        for _ in range(40):                                  # about ten seconds of the match
            rx, rz, bx = position(game_level, REFEREE, "X"), position(game_level, REFEREE, "Z"), position(game_level, BALL, "X")
            xs.append(rx); zs.append(rz)
            near += abs(rx - bx) < 4.0
            time.sleep(0.25)
        assert max(zs) - min(zs) < 0.6, f"he stays on his line (z does not change): {min(zs):.2f}..{max(zs):.2f}"
        assert abs(abs(sum(zs) / len(zs)) - 6.0) < 0.5, f"the line is inside the touchline (z = +-(HalfWidth - 1)): {sum(zs) / len(zs):.2f}"
        assert max(xs) - min(xs) > 4.0, f"he walks along it, with the ball: x went {min(xs):.2f}..{max(xs):.2f}"
        assert near >= 20, f"and is across from the ball most of the time: {near} of 40"
    finally:
        editor.cmd("Stop -Keep false")
        editor.wait_play_state("Stopped")
