"""Game.dll hot reload: a changed game module is rebuilt and every world is destroyed and recreated around the swap.

Play is what triggers it. The recompile-check finds the DLL stale (its inputs are newer), rebuilds the script project (tens of seconds), swaps the DLL and
restores the open level in a fresh world before entering Play. The level must come back exactly as it was.
"""
import os
import pytest
from pathlib import Path

from harness import REPO

GAME_SOURCE = REPO / "plugins" / "xscript_module.plugin" / "source" / "Runtime" / "xscript_game_entry.cpp"


def test_play_after_a_game_source_change_reloads_the_module_and_keeps_the_level(editor, game_level):
    if "the project has no script modules" in editor.log_text():
        pytest.skip("the example project has no script modules, so there is no Game.dll to rebuild")
    before = {scene: game_level.entities(scene) for scene, _ in game_level.scenes}
    reloads_before = editor.log_text().count("[Vn restore]")

    os.utime(GAME_SOURCE)                               # looks edited: the module is now older than its source
    assert editor.cmd("Play").startswith("Play requested")
    editor.wait_play_state("Playing", timeout=240)      # includes the module rebuild

    log = editor.log_text()
    assert "Game.dll: rebuild succeeded" in log
    assert log.count("[Vn restore]") == reloads_before + 1, "the world should have been rebuilt exactly once"
    assert {scene: game_level.entities(scene) for scene, _ in game_level.scenes} == before
    assert game_level.ed.sessions()[0].name == game_level.name
    # the reload's bridge file is this process's own (its name carries the process id, so a second editor on the same Level cannot collide with it) and is gone
    # once it has been read
    import tempfile
    assert not list(Path(tempfile.gettempdir()).glob(f"xGPU_LevelEditor_ReloadBridge_{editor.proc.pid}_*.bin")), "the bridge file is removed after the reload"
    assert "snapshot restore failed" not in log, log[log.find("snapshot restore failed") - 200:][:600]

    assert editor.cmd("Stop") == "Stop requested"
    editor.wait_play_state("Stopped")
    assert {scene: game_level.entities(scene) for scene, _ in game_level.scenes} == before


def test_a_reload_whose_snapshot_brings_nothing_back_reopens_the_level_instead_of_crashing(editor, game_level):
    """The scenes of a reload are moved back into the rebuilt world and trust the snapshot to have brought every entity back. When it did not (a snapshot
    that cannot be read) they name entities the new world never made: the Level tree and the save behind Play used to assert on the first of them. The
    editor now notices, says so (GAME.MODULE.RELOAD_STATE_LOST), and rebuilds the world from the saved level."""
    if "the project has no script modules" in editor.log_text():
        pytest.skip("the example project has no script modules, so there is no Game.dll to rebuild")
    before = {scene: game_level.entities(scene) for scene, _ in game_level.scenes}
    assert game_level.cmd("SimulateSnapshotFailure -State on") == "SimulateSnapshotFailure: on"
    try:
        os.utime(GAME_SOURCE)
        assert editor.cmd("Play").startswith("Play requested")
        editor.wait_play_state("Playing", timeout=240)

        assert editor.alive()
        log = editor.log_text()
        assert "snapshot restore failed: simulated" in log
        assert "reopening the Level from its last save" in log
        assert "GAME.MODULE.RELOAD_STATE_LOST" in editor.cmd("LogProblems -Query code:GAME.MODULE.RELOAD_STATE_LOST"), "the Logs say what happened"
        assert {scene: game_level.entities(scene) for scene, _ in game_level.scenes} == before, "the level is back from its last save"

        assert editor.cmd("Stop") == "Stop requested"
        editor.wait_play_state("Stopped")
        assert {scene: game_level.entities(scene) for scene, _ in game_level.scenes} == before
    finally:
        game_level.cmd("SimulateSnapshotFailure -State off")
