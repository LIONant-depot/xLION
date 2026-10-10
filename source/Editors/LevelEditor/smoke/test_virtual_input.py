"""The virtual mouse and keyboard of the editor (dependencies/xGPU/source/Details/xgpu_virtual_input.h, the commands in LevelEditor_Commands_VirtualInput.h).

While VirtualInput is on, the machine's own mouse and keys are ignored and the editor takes its input from the commands: a test (or an assistant) drives the window editor without fighting the
person at the computer for the one real mouse. These tests check that what is sent is what ImGui sees, and that the machine's mouse is not what moves it.
"""
import re
import time

import pytest

pytestmark = pytest.mark.needs_window          # the input is read by the window editor's ImGui backend


def frames(editor) -> int:
    return int(re.search(r"InputFrames: (\d+)", editor.cmd("InputFrames"))[1])


def wait_frames(editor, count: int = 3) -> None:
    """Waits until the editor has read the virtual input in `count` more frames: what was sent has been seen."""
    start = frames(editor)
    deadline = time.monotonic() + 10
    while frames(editor) < start + count:
        assert time.monotonic() < deadline, "the editor does not read the virtual input (no frames)"
        time.sleep(0.02)


def state(editor) -> dict:
    reply = editor.cmd("InputState")
    assert reply.startswith("InputState: "), reply
    out = dict(re.findall(r"(\w+)=(\S+)", reply))
    for key in ("imgui", "sent"):
        if key in out and "," in out[key]:
            x, y = out[key].split(",")
            out[key] = (float(x), float(y))
    return out


@pytest.fixture
def virtual(editor):
    assert editor.cmd("VirtualInput -On true") == "VirtualInput: on"
    wait_frames(editor)
    yield editor
    editor.cmd("VirtualInput -On false")


def test_the_commands_say_so_when_virtual_input_is_off(editor):
    assert editor.cmd("VirtualInput -On false") == "VirtualInput: off"
    assert "VirtualInput -On true" in editor.cmd("MouseMove -X 10 -Y 10"), "an input command explains how to turn it on"
    assert "not true or false" in editor.cmd("VirtualInput -On maybe")


def test_the_virtual_mouse_moves_the_mouse_imgui_sees(virtual):
    virtual.cmd("MouseMove -X 300 -Y 200")
    wait_frames(virtual)
    first = state(virtual)["imgui"]
    virtual.cmd("MouseMove -X 400 -Y 260")
    wait_frames(virtual)
    second = state(virtual)["imgui"]
    assert (second[0] - first[0], second[1] - first[1]) == (100.0, 60.0), f"a move of 100,60 was seen as {first} -> {second}"


def test_the_machines_mouse_is_ignored_while_virtual_input_is_on(virtual):
    virtual.cmd("MouseMove -X 500 -Y 300")
    wait_frames(virtual)
    seen = state(virtual)["imgui"]
    time.sleep(0.5)                                         # whatever the real mouse does meanwhile (the person at the computer keeps using it)
    wait_frames(virtual)
    assert state(virtual)["imgui"] == seen, "the mouse of ImGui follows only the virtual one"


def test_a_virtual_button_is_pressed_and_released(virtual):
    virtual.cmd("MouseMove -X 500 -Y 300")
    virtual.cmd("MouseButton -Button left -Down true")
    wait_frames(virtual)
    assert state(virtual)["down"] == "L--" or state(virtual)["down"].startswith("L"), state(virtual)
    virtual.cmd("MouseButton -Button left -Down false")
    wait_frames(virtual)
    assert state(virtual)["down"] == "---"
    virtual.cmd("MouseButton -Button right -Down true")
    wait_frames(virtual)
    assert state(virtual)["down"] == "--R"
    virtual.cmd("MouseButton -Button right -Down false")
    wait_frames(virtual)
    assert "is not left" in virtual.cmd("MouseButton -Button hat -Down true")


def test_a_virtual_key_is_seen_as_a_modifier(virtual):
    virtual.cmd("Key -Key LCONTROL -Down true")
    wait_frames(virtual)
    assert state(virtual)["ctrl"] == "1"
    virtual.cmd("Key -Key LCONTROL -Down false")
    wait_frames(virtual)
    assert state(virtual)["ctrl"] == "0"
    assert "is not a key name" in virtual.cmd("Key -Key Banana -Down true")


def test_turning_it_off_gives_the_machine_its_input_back_and_clears_what_was_held(editor):
    editor.cmd("VirtualInput -On true")
    editor.cmd("MouseButton -Button left -Down true")
    editor.cmd("Key -Key LCONTROL -Down true")
    wait_frames(editor)
    assert editor.cmd("VirtualInput -On false") == "VirtualInput: off"
    editor.cmd("VirtualInput -On true")
    s = editor.cmd("InputState")
    editor.cmd("VirtualInput -On false")
    assert "buttons=---" in s, "a fresh start: nothing stays pressed from before"
