"""More game module reload tests: component list, stop after reload, reload while paused."""
import os
from pathlib import Path

from harness import REPO

GAME_SOURCE = REPO / "plugins" / "xscript_module.plugin" / "source" / "Runtime" / "xscript_game_entry.cpp"


def test_list_component_types_after_reload(level):
    """ListComponentTypes is the same after a game module reload."""
    editor = level.ed
    
    before = editor.cmd("ListComponentTypes")
    
    os.utime(GAME_SOURCE)
    editor.cmd("Play")
    editor.wait_play_state("Playing", timeout=240)
    
    # Component types should be the same
    after = editor.cmd("ListComponentTypes")
    assert before == after
    
    editor.cmd("Stop")
    editor.wait_play_state("Stopped")


def test_stop_after_reload_restores_level(level):
    """Stop after a reload restores the level."""
    editor = level.ed
    before = {scene: level.entities(scene) for scene, _ in level.scenes}
    
    os.utime(GAME_SOURCE)
    editor.cmd("Play")
    editor.wait_play_state("Playing", timeout=240)
    
    editor.cmd("Stop")
    editor.wait_play_state("Stopped")
    
    after = {scene: level.entities(scene) for scene, _ in level.scenes}
    assert before == after


def test_reload_while_paused(level):
    """Reload while Paused."""
    editor = level.ed
    
    editor.cmd("Play")
    editor.wait_play_state("Playing")
    
    editor.cmd("Pause")
    editor.wait_play_state("Paused")
    
    os.utime(GAME_SOURCE)
    editor.cmd("Play")
    editor.wait_play_state("Playing", timeout=240)
    
    editor.cmd("Stop")
    editor.wait_play_state("Stopped")
