"""A game module that crashes while it registers its systems must not take the editor down.

SimulateModuleCrash makes the module's RegisterSystems crash on purpose (an access violation, the way a system that queries a component it never
told the DLL about does) the next time a world registers its systems. The editor has to say so, throw the half built world away, carry on
with the host's systems only, and use the module again once the cause is gone.
"""
import re
import pytest


CRASH_LINE = "Game.dll crashed while registering its systems"


def _status(editor_or_level) -> dict:
    reply = editor_or_level.cmd("GameModuleStatus")
    return dict(re.findall(r"^(Loaded|Crashed)=(\w+)$", reply, re.M)) | {"text": reply}


@pytest.fixture
def module_level(game_level):
    """A Level that names a Game, with its game module loaded (the Level's own: a Level with no Game has none); whatever a test does, the module and Play are put back at the end."""
    level = game_level
    assert _status(level)["Loaded"] == "true", "the Soccer level's Game is loaded for it"
    yield level
    level.cmd("SimulateModuleCrash -State off")
    if level.ed.play_state().startswith("Playing") or "Paused" in level.ed.play_state():
        level.ed.cmd("Stop")
        level.ed.wait_play_state("Stopped")


def test_game_module_status_reports_the_module(level):
    status = _status(level)
    assert status["Loaded"] in ("true", "false")
    assert status["Crashed"] == "false", "a freshly opened editor has a module that did not crash"


def test_simulate_module_crash_needs_on_or_off(level):
    assert "on|off" in level.cmd("SimulateModuleCrash -State maybe")
    assert _status(level)["Crashed"] == "false"


def test_a_module_that_crashes_registering_does_not_take_the_editor_down(module_level):
    level, editor = module_level, module_level.ed
    before = {scene: level.entities(scene) for scene, _ in level.scenes}

    assert level.cmd("SimulateModuleCrash -State on") == "SimulateModuleCrash: on"
    assert editor.cmd("Play").startswith("Play requested")        # makes a fresh world: the module registers its systems into it
    editor.wait_play_state("Playing", timeout=240)

    status = _status(level)
    assert status["Crashed"] == "true"
    assert "crashed while registering its systems" in status["text"]
    assert editor.alive(), "the editor must still be running"
    assert {scene: level.entities(scene) for scene, _ in level.scenes} == before, "the level must come back as it was, in the new world"

    assert editor.cmd("Stop") == "Stop requested"
    editor.wait_play_state("Stopped")
    assert editor.alive()
    assert {scene: level.entities(scene) for scene, _ in level.scenes} == before


def test_the_crash_is_reported_in_the_log(module_level):
    level, editor = module_level, module_level.ed
    level.cmd("SimulateModuleCrash -State on")
    editor.cmd("Play")
    editor.wait_play_state("Playing", timeout=240)
    assert "Game.dll crashed while registering its systems" in editor.log_text()


def test_a_crashed_module_stays_out_until_the_cause_is_gone(module_level):
    """After the crash the module is flagged: a second world does not call it again (no second crash), and 'off' lets it run again."""
    level, editor = module_level, module_level.ed
    reported = editor.log_text().count(CRASH_LINE)                # the log is shared by every test
    level.cmd("SimulateModuleCrash -State on")
    editor.cmd("Play")
    editor.wait_play_state("Playing", timeout=240)
    editor.cmd("Stop")
    editor.wait_play_state("Stopped")
    assert _status(level)["Crashed"] == "true"
    first = editor.log_text().count(CRASH_LINE)
    assert first > reported, "the crash must have been reported"

    editor.cmd("Play")                                            # another world: the flagged module is skipped
    editor.wait_play_state("Playing", timeout=240)
    assert editor.log_text().count(CRASH_LINE) == first, "a flagged module must not be called again"
    editor.cmd("Stop")
    editor.wait_play_state("Stopped")

    assert level.cmd("SimulateModuleCrash -State off") == "SimulateModuleCrash: off"
    assert _status(level)["Crashed"] == "false"
    editor.cmd("Play")                                            # the module registers normally again
    editor.wait_play_state("Playing", timeout=240)
    assert _status(level)["Crashed"] == "false"
    assert editor.log_text().count(CRASH_LINE) == first, "the module runs again without a new crash"
    editor.cmd("Stop")
    editor.wait_play_state("Stopped")


def test_the_module_of_one_level_crashing_does_not_touch_another_level(editor, game_level):
    """Every Level has a game module of its own: the switches and the status are addressed to a Level, and a crash in one is not seen by the other."""
    other = next(n for g, n in editor.levels() if g != "0166FAE5EB82F3F3" and n != game_level.name)
    assert editor.cmd(f"OpenLevel -Level {next(g for g, n in editor.levels() if n == other)} -Save 0").startswith("Opened Level")
    try:
        assert game_level.cmd("SimulateModuleCrash -State on") == "SimulateModuleCrash: on"
        mine = dict(re.findall(r"^(Loaded|Crashed)=(\w+)$", game_level.cmd("GameModuleStatus"), re.M))
        theirs = dict(re.findall(r"^(Loaded|Crashed)=(\w+)$", editor.cmd(f"{other}\\GameModuleStatus"), re.M))
        assert mine["Loaded"] == "true"
        assert theirs == {"Loaded": "false", "Crashed": "false"}, "a Level of no Game has no module to crash"
        assert editor.cmd(f"{other}\\SimulateModuleCrash -State on") == "SimulateModuleCrash: on"
        assert dict(re.findall(r"^(Loaded|Crashed)=(\w+)$", game_level.cmd("GameModuleStatus"), re.M))["Crashed"] == "false", "the switch of the other Level did not reach this one"
    finally:
        game_level.cmd("SimulateModuleCrash -State off")
        editor.cmd(f"{other}\\SimulateModuleCrash -State off")
        editor.cmd(f"{other}\\Close -Save 0")
