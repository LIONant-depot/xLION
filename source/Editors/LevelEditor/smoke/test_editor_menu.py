"""The menu at the left of every editor's top bar (the icon of the resource type and a down arrow, one button): Save, Save All and Close.

Save All fires the editor's Save All event: every open editor that has something pending saves it (and the asset database, and anything else that subscribed); Close closes the editor, and with something unsaved it first asks - Save, Don't Save or Cancel.
The menu and the question are the host's (xeditor::open_resource_editors), the same for every resource editor, and what they do is also a command, so these tests drive the commands
(SaveAll, CloseResourceEditor -Save true|false|ask|cancel); the buttons themselves were pressed with the real mouse when they were made.

The Texture "bricks" of the example project is the editor that is changed; the project guard puts what a test wrote back.
"""
import re

import pytest

from harness import REPO

def descriptor_of(texture):
    """The Descriptor.txt of the texture the test opened (which texture it is depends on what the asset tree lists first): Descriptors/Texture/<byte 0>/<byte 1>/<instance>.desc"""
    instance = texture.guid[:16]
    return REPO / "example.lionprj" / "Descriptors" / "Texture" / instance[-2:] / instance[-4:-2] / f"{instance}.desc" / "Descriptor.txt"


@pytest.fixture
def texture(editor):
    """The Texture editor of the example project's first texture, opened clean."""
    found = editor.find_asset("Texture")
    if found is None:
        pytest.skip("the example project has no compiled Texture asset")
    guid, name = found
    assert editor.cmd(f"OpenResourceEditor -Asset {guid} -Library {editor.libraries()[0][0]}") == ""
    yield type("Texture", (), {"ed": editor, "guid": guid, "name": name})
    editor.cmd(f"CloseResourceEditor -Asset {guid} -Save false")


def dirty(editor, name: str) -> bool:
    return next(s.dirty for s in editor.sessions() if s.name == name)


def is_open(editor, name: str) -> bool:
    return any(s.name == name for s in editor.sessions())


def change(texture, quality: float) -> None:
    texture.ed.cmd(f"{texture.name}\\SetProperty -Path Texture/Quality -Value {quality}")
    assert dirty(texture.ed, texture.name)


def close(texture, how: str) -> str:
    return texture.ed.cmd(f"CloseResourceEditor -Asset {texture.guid} -Save {how}")


def test_save_all_saves_every_editor_that_has_something_pending(level, texture):
    editor = level.ed
    change(texture, 0.6)
    level.ok(f"CreateEntity -Scene {level.scene} -Id 7E58A001 -Folder 0")
    assert dirty(editor, level.name) and dirty(editor, texture.name)

    reply = editor.cmd("SaveAll", allow_disk=True)
    assert re.match(r"SaveAll: saved [2-9]: ", reply), reply         # the two editors (and the resource database, when a save of theirs left something in it)
    assert texture.name in reply and level.name in reply, "both are named"
    assert not dirty(editor, level.name) and not dirty(editor, texture.name), "nothing is pending any more"
    assert "#3F19999A" in descriptor_of(texture).read_text(), "the texture's change is on disk (0.6)"


def test_save_all_with_nothing_pending_says_so(texture):
    assert texture.ed.cmd("SaveAll", allow_disk=True) == "SaveAll: nothing was pending"


def test_close_with_the_changes_saved_saves_them_first(texture):
    change(texture, 0.6)
    assert close(texture, "true") == ""
    assert not is_open(texture.ed, texture.name)
    assert "#3F19999A" in descriptor_of(texture).read_text(), "saved, then closed"


def test_close_with_the_changes_dropped_leaves_the_file_alone(texture):
    before = descriptor_of(texture).read_bytes()
    change(texture, 0.6)
    assert close(texture, "false") == ""
    assert not is_open(texture.ed, texture.name)
    assert descriptor_of(texture).read_bytes() == before, "Don't Save: nothing was written"


def test_close_asks_when_something_is_pending_and_cancel_keeps_the_editor(texture):
    change(texture, 0.6)
    assert "asking whether to save the changes of" in close(texture, "ask")
    assert "the question is already open" in close(texture, "ask"), "one question for one editor"
    assert is_open(texture.ed, texture.name), "the editor stays open while the question is open"
    assert "cancelled" in close(texture, "cancel")
    assert is_open(texture.ed, texture.name) and dirty(texture.ed, texture.name), "Cancel: nothing changed"
    assert "no question to cancel" in close(texture, "cancel")


def test_close_asks_nothing_when_nothing_is_pending(texture):
    assert close(texture, "ask") == ""
    assert not is_open(texture.ed, texture.name)


def test_close_refuses_what_it_does_not_know(texture):
    assert "-Save is true, false, ask or cancel" in close(texture, "maybe")
    assert is_open(texture.ed, texture.name)
