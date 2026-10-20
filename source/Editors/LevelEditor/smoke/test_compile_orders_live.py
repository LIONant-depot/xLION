"""Compilation orders in the running editor (dependencies/xresource_pipeline_v2/source/editor/xresource_editor_compile_orders.h, library_mgr::RequestCompile /
CancelCompile): Compile makes an order at once (the editor does not wait for the file monitor), the order is the manager's - an editor closed and opened again
still sees it, Compile again gives the same order, Cancel takes a waiting order out of the queue - and an order is over when everything its compile made is.
The Arial font (its atlas is made by its compile) is the resource; the queue is paused so the order waits, and always resumed.
"""
import re
import time

import pytest

from harness import quote

FONT = "5549D8C8E92200013285CB58BB79E1AD"          # Arial, MTSDF (Descriptors/Font/01/00)


def _state(editor) -> str:
    return re.search(r"state: ([^\n]*)", editor.cmd(f"ResourceEditorCommand -Asset {FONT} -Cmd CompileStatus"))[1]


def _wait(editor, done, seconds=60):
    deadline = time.time() + seconds
    while time.time() < deadline:
        state = _state(editor)
        if done(state):
            return state
        time.sleep(0.05)
    pytest.fail(f"the state never became what the test waits for (last: {_state(editor)})")


@pytest.fixture
def font_editor(editor):
    lib = editor.libraries()[0][0]
    editor.ok(f"OpenResourceEditor -Asset {FONT} -Library {lib}", timeout=30)
    editor.cmd("CompilePause -State false")
    _wait(editor, lambda s: not s.startswith(("queued", "compiling")))          # whatever the startup scan left
    yield lib
    editor.cmd("CompilePause -State false")
    editor.cmd(f"CloseResourceEditor -Asset {FONT}")


def test_compile_makes_an_order_at_once_and_it_is_over_only_when_what_it_made_is(editor, font_editor):
    reply = editor.cmd(f"ResourceEditorCommand -Asset {FONT} -Cmd Compile")
    assert re.search(r"compile queued \(order \d+\)", reply), reply
    seen = []
    deadline = time.time() + 60
    while time.time() < deadline:
        state = _state(editor)
        if not seen or seen[-1] != state:
            seen.append(state)
        if state.startswith(("success", "failed", "cancelled")):
            break
        time.sleep(0.01)
    assert seen[0].startswith(("queued", "compiling")), f"the editor knew of the compile when it was asked for: {seen}"
    assert seen[-1].startswith("success"), seen


def test_a_waiting_order_is_cancelled_out_of_the_queue_and_the_resource_compiles_again_after(editor, font_editor):
    editor.cmd("CompilePause -State true")
    editor.cmd(f"ResourceEditorCommand -Asset {FONT} -Cmd Compile")
    assert _state(editor).startswith("queued"), "paused: the order waits"
    assert int(re.search(r"Waiting=(\d+)", editor.cmd("CompileStatus"))[1]) >= 1, "it is in the queue"

    assert "cancelling" in editor.cmd(f"ResourceEditorCommand -Asset {FONT} -Cmd CancelCompile")
    assert _state(editor).startswith("cancelled"), "the order ended as cancelled without a worker"
    assert "Waiting=0" in editor.cmd("CompileStatus"), "it left the queue"
    assert "no compile is running" in editor.cmd(f"ResourceEditorCommand -Asset {FONT} -Cmd CancelCompile"), "a second cancel finds no order"

    editor.cmd("CompilePause -State false")
    editor.cmd(f"ResourceEditorCommand -Asset {FONT} -Cmd Compile")
    assert _wait(editor, lambda s: s.startswith(("success", "failed", "cancelled"))).startswith("success"), "the resource compiles after a cancel"


def test_the_order_is_the_managers_not_the_editors(editor, font_editor):
    """Close the editor and open another one on the same resource while the order waits: it still sees it (Cancel would be shown); Compile again is the same order."""
    editor.cmd("CompilePause -State true")
    first = re.search(r"order (\d+)", editor.cmd(f"ResourceEditorCommand -Asset {FONT} -Cmd Compile"))[1]
    editor.cmd(f"CloseResourceEditor -Asset {FONT}")
    editor.ok(f"OpenResourceEditor -Asset {FONT} -Library {font_editor}", timeout=30)
    assert _state(editor).startswith("queued"), "the new editor finds the order of its resource"

    again = re.search(r"order (\d+)", editor.cmd(f"ResourceEditorCommand -Asset {FONT} -Cmd Compile"))[1]
    assert again == first, "Compile while an order is open gives that order"

    editor.cmd(f"ResourceEditorCommand -Asset {FONT} -Cmd CancelCompile")        # the new editor cancels what the old one asked for
    assert _state(editor).startswith("cancelled")
