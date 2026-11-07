"""The three moves of the Soccer example's players (soccer_player_system.h): a goalkeeper DIVES at a ball he cannot reach on his feet, a field player LOFTS a
shot from farther out or over a defender, and a field player SLIDES at a ball an opponent has at his feet. The players system counts them in the match
(SoccerMatch/Dives, Lofts, Tackles).

The real game, played. The moves come out of the match itself (a test cannot throw the ball: SetProperty on its Transform teleports it, standing still), so
these tests watch a match: the counters start at zero, they never go down, and in a few minutes of play the moves happen. The second test is OBSERVATIONAL -
it depends on how the match goes, so it gets a margin over the time they took.
"""
import time

SCENE = "5B388EFC2203EC6F"
PITCH = "00001000"                              # the entity with the match (the floor)
WATCH_SECONDS = 60.0  # all three moves happened within ~18 s of Play on 2026-11-07 (the match is deterministic): 60 s is margin


def match(level, what: str) -> str:
    return level.ed.cmd(f"{level.name}\\GetProperty -Scene {SCENE} -Id {PITCH} -Component SoccerMatch -Path SoccerMatch/{what}")


def counters(level) -> dict:
    return {name: int(match(level, name)) for name in ("Dives", "Lofts", "Tackles")}


def wait_for_phase(level, phase: str, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if match(level, "Phase") == phase:
            return
        time.sleep(0.1)
    raise AssertionError(f"the match did not get to {phase}: {match(level, 'Phase')}")


def test_the_counters_of_the_moves_start_at_zero(game_level):
    assert counters(game_level) == {"Dives": 0, "Lofts": 0, "Tackles": 0}


def test_the_players_dive_loft_and_slide_in_a_match(game_level):
    editor = game_level.ed
    assert editor.cmd("Play", allow_disk=True).startswith("Play requested")
    editor.wait_play_state("Playing", timeout=240)
    try:
        wait_for_phase(game_level, "Playing")
        seen = counters(game_level)
        deadline = time.monotonic() + WATCH_SECONDS
        while time.monotonic() < deadline and not all(seen.values()):
            now = counters(game_level)
            for name, value in now.items():
                assert value >= seen[name], f"{name} went down: {seen[name]} -> {value}"
            seen = now
            time.sleep(0.5)
        print(f"the moves after {WATCH_SECONDS - max(0.0, deadline - time.monotonic()):.1f} s of play: {seen}")
        assert seen["Lofts"] > 0, f"no lofted shot in {WATCH_SECONDS:.0f} s of play: {seen}"
        assert seen["Dives"] > 0, f"no goalkeeper dive in {WATCH_SECONDS:.0f} s of play: {seen}"
        assert seen["Tackles"] > 0, f"no slide tackle took the ball in {WATCH_SECONDS:.0f} s of play: {seen}"
    finally:
        editor.cmd("Stop -Keep false")
        editor.wait_play_state("Stopped")
