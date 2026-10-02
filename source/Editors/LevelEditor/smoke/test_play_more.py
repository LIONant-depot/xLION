"""More play tests: pause/resume, step refusal, keep/discards tweaks."""
import time
import pytest
from harness import b64


def test_pause_resume(level):
    """Pause/Resume (Play again while Paused)."""
    editor = level.ed
    
    editor.cmd("Play")
    editor.wait_play_state("Playing")
    
    editor.cmd("Pause")
    editor.wait_play_state("Paused")
    
    editor.cmd("Play")
    editor.wait_play_state("Playing")


def test_step_from_playing_refused(level):
    """Step from Playing is refused."""
    editor = level.ed
    
    editor.cmd("Play")
    editor.wait_play_state("Playing")
    
    assert "pause first" in editor.cmd("Step")


def test_stop_twice(level):
    """Stop twice - first stops, second should refuse."""
    editor = level.ed
    
    editor.cmd("Play")
    editor.wait_play_state("Playing")
    
    editor.cmd("Stop")
    editor.wait_play_state("Stopped")
    
    assert "already stopped" in editor.cmd("Stop")


def test_play_while_playing(level):
    """Play while Playing."""
    editor = level.ed
    
    editor.cmd("Play")
    editor.wait_play_state("Playing")
    
    assert "already playing" in editor.cmd("Play")


def test_get_play_state_fields(level):
    """GetPlayState fields after each transition."""
    editor = level.ed
    
    # Stopped
    assert editor.play_state() == "Stopped"
    
    editor.cmd("Play")
    editor.wait_play_state("Playing")
    
    # Playing
    state = editor.cmd("GetPlayState")
    assert "Building=false" in state
    assert "PlayState=Playing" in state
    
    editor.cmd("Pause")
    editor.wait_play_state("Paused")
    
    # Paused
    state = editor.cmd("GetPlayState")
    assert "PlayState=Paused" in state
    
    editor.cmd("Stop")
    editor.wait_play_state("Stopped")
    
    # Back to Stopped
    assert editor.play_state() == "Stopped"


def test_editing_commands_during_play(level):
    """Editing commands are allowed during Play (they are play tweaks); Stop -Keep false discards them."""
    editor = level.ed

    editor.cmd("Play")
    editor.wait_play_state("Playing")

    level.ok(f"CreateEntity -Scene {level.scene} -Id 7E57FFFF -Folder 0")
    assert "7E57FFFF" in level.entities()

    editor.cmd("Stop -Keep false")
    editor.wait_play_state("Stopped")
    assert "7E57FFFF" not in level.entities()


def test_stop_keep_true(level):
    """Stop -Keep true keeps a SetProperty made during Play."""
    editor = level.ed
    scene, entity, transform = level.find_with_component("Transform")
    path = "Transform/Position/X"
    original = editor.property_value(level.name, scene, entity, path)
    type_guid = level.property_type(entity, path, scene)
    
    editor.cmd("Play")
    editor.wait_play_state("Playing")
    
    level.ok(f"SetProperty -Scene {scene} -Id {entity} -Component {transform} -Path {b64(path)}"
             f" -TypeGuid {type_guid} -Before {b64(original)} -After {b64('5.000000')}")
    assert editor.property_value(level.name, scene, entity, path) == "5.000000"
    
    editor.cmd("Stop -Keep true")
    editor.wait_play_state("Stopped")
    
    assert editor.property_value(level.name, scene, entity, path) == "5.000000"
    
    # Undo should revert
    level.cmd("Undo")
    assert editor.property_value(level.name, scene, entity, path) == original


def test_stop_keep_false(level):
    """Stop -Keep false discards a SetProperty made during Play."""
    editor = level.ed
    scene, entity, transform = level.find_with_component("Transform")
    path = "Transform/Position/X"
    original = editor.property_value(level.name, scene, entity, path)
    type_guid = level.property_type(entity, path, scene)
    
    editor.cmd("Play")
    editor.wait_play_state("Playing")
    
    level.ok(f"SetProperty -Scene {scene} -Id {entity} -Component {transform} -Path {b64(path)}"
             f" -TypeGuid {type_guid} -Before {b64(original)} -After {b64('5.000000')}")
    assert editor.property_value(level.name, scene, entity, path) == "5.000000"
    
    editor.cmd("Stop -Keep false")
    editor.wait_play_state("Stopped")
    
    assert editor.property_value(level.name, scene, entity, path) == original


@pytest.mark.parametrize("scale", ["0.25", "3"], ids=["slow_most_frames_have_no_step", "fast_most_frames_have_several_steps"])
def test_transform_edit_during_play_survives_every_kind_of_frame(level, scale):
    """Slow: most frames have no fixed step due, and the physics must not read the old pose back over an edit made in between. Fast: several steps
    run in one frame, and the edit must reach the body in the first of them and survive the rest."""
    editor = level.ed
    scene, entity, transform = level.find_with_component("Transform")
    path = "Transform/Position/X"
    original = editor.property_value(level.name, scene, entity, path)
    type_guid = level.property_type(entity, path, scene)

    assert "done" in level.cmd(f"SetTimeScale -Scale {scale}")
    try:
        editor.cmd("Play")
        editor.wait_play_state("Playing")
        level.ok(f"SetProperty -Scene {scene} -Id {entity} -Component {transform} -Path {b64(path)}"
                 f" -TypeGuid {type_guid} -Before {b64(original)} -After {b64('5.000000')}")
        for _ in range(20):                                    # a second of frames, most of them with no step
            assert editor.property_value(level.name, scene, entity, path) == "5.000000"
            time.sleep(0.05)
    finally:
        level.cmd("SetTimeScale -Scale 1")
        editor.cmd("Stop -Keep false")
        editor.wait_play_state("Stopped")
