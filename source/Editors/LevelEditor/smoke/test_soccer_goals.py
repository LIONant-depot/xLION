"""The goals of the Soccer example: the physics tells the game that the ball entered the trigger box in a goal (sensor_begin_event) and the goal system gives the point to the team that does not
defend it - only while the match is being played.

The real game, played: the ball is put into a goal with SetProperty (the physics takes the new position of its Transform) and the score of the match is read from the pitch.
"""
import time

SCENE = "5B388EFC2203EC6F"
PITCH, BALL = "00001000", "00005000"            # the entity with the match (the floor) and the ball
BLUE_GOAL_X, RED_GOAL_X = -13, 13                # Blue defends the goal at -x, Red the one at +x


def match(level, what: str) -> str:
    return level.ed.cmd(f"{level.name}\\GetProperty -Scene {SCENE} -Id {PITCH} -Component SoccerMatch -Path SoccerMatch/{what}")


def score(level) -> tuple:
    return int(match(level, "ScoreBlue")), int(match(level, "ScoreRed"))


def wait_for_phase(level, phase: str, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if match(level, "Phase") == phase:
            return
        time.sleep(0.1)
    raise AssertionError(f"the match did not get to {phase}: {match(level, 'Phase')}")


def put_the_ball_in(level, x: int) -> None:
    for axis, value in (("Z", 0), ("X", x)):
        level.ed.cmd(f"{level.name}\\SetProperty -Scene {SCENE} -Id {BALL} -Component Transform -Path Transform/Position/{axis} -After {value}")
    time.sleep(0.5)


def test_the_ball_in_a_goal_scores_for_the_team_that_does_not_defend_it(game_level):
    editor = game_level.ed
    assert editor.cmd("Play", allow_disk=True).startswith("Play requested")
    editor.wait_play_state("Playing", timeout=240)
    try:
        wait_for_phase(game_level, "Playing")
        blue, red = score(game_level)
        put_the_ball_in(game_level, RED_GOAL_X)
        assert score(game_level) == (blue + 1, red), "the ball in the goal Red defends is a goal for Blue"
        assert match(game_level, "LastScorer") == "Blue"

        wait_for_phase(game_level, "Playing")
        blue, red = score(game_level)
        put_the_ball_in(game_level, BLUE_GOAL_X)
        assert score(game_level) == (blue, red + 1), "the ball in the goal Blue defends is a goal for Red"
        assert match(game_level, "LastScorer") == "Red"
    finally:
        editor.cmd("Stop -Keep false")
        editor.wait_play_state("Stopped")


def test_a_ball_in_a_goal_when_the_match_is_not_being_played_is_not_a_goal(game_level):
    editor = game_level.ed
    assert editor.cmd("Play", allow_disk=True).startswith("Play requested")
    editor.wait_play_state("Playing", timeout=240)
    try:
        wait_for_phase(game_level, "Playing")
        put_the_ball_in(game_level, RED_GOAL_X)
        assert match(game_level, "Phase") == "Goal"
        before = score(game_level)
        put_the_ball_in(game_level, BLUE_GOAL_X)                     # during the celebration
        assert score(game_level) == before, "one goal is one point: the net holds the ball while everybody celebrates"
    finally:
        editor.cmd("Stop -Keep false")
        editor.wait_play_state("Stopped")
