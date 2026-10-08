"""The Scene Editor (documentation/Editors/prefabs_plan.md, "Scene Editor"): a Scene opened by itself - a double click on it in the Asset Browser, OpenScene, OpenResourceEditor - is the document of an editor of
its own (the Level editor with a Scene as its document, as a Prefab Editor has a prefab). It is not added to any Level (a Level gets a Scene by dropping it on it, or AddScene), one writer per Scene (a Scene a
Level already has open is not opened again: that editor is brought to the front and the reply says so), a click is not an unsaved change, and a clean editor closes without asking.

  Game: a Scene names none, so the editor works under the Game of the Level it was opened from, else the project's only Game (in memory, nothing is written).
"""
import re
import shutil
import tempfile
import time
from pathlib import Path

import pytest
from test_prefabs import _guid_folder

PHYSICS = "A1B2C3D4E5F60719"            # the Physics scene (the Level of the tests, MyTestLevel, has it)
PITCH = "5B388EFC2203EC6F"              # the Soccer pitch (the Soccer Level has it, and needs the Soccer Game's module)


class SceneEditor:
    def __init__(self, ed, guid: str, name: str) -> None:
        self.ed, self.guid, self.name = ed, guid, name

    def cmd(self, line: str, **kw) -> str:
        return self.ed.cmd(f"{self.name}\\{line}", **kw)

    def ok(self, line: str, **kw) -> None:
        self.ed.ok(f"{self.name}\\{line}", **kw)

    def entities(self) -> dict:
        return self.ed.entities(self.name, self.guid)

    def dirty(self) -> bool:
        return next(s.dirty for s in self.ed.sessions() if s.name == self.name)

    def close(self) -> None:
        if self.name in [s.name for s in self.ed.sessions()]:
            self.cmd("Close -Save 0")
        deadline = time.monotonic() + 15
        while self.name in [s.name for s in self.ed.sessions()] and time.monotonic() < deadline:
            time.sleep(0.2)


def _open(ed, scene: str, name: str) -> SceneEditor:
    reply = ed.cmd(f"OpenScene -Scene {scene}", timeout=240)
    assert reply.startswith("Opened Scene"), reply
    ed.wait_for("GetPlayState", r"Building=false", timeout=240)
    return SceneEditor(ed, scene, name)


@pytest.fixture
def physics_scene_restored():
    """The tests save the Physics scene: its folder is put back as it was."""
    folder = _guid_folder("Scene", PHYSICS)
    backup = Path(tempfile.mkdtemp(prefix="xlion_scene_editor_"))
    shutil.copytree(folder, backup / "scene")
    yield
    for attempt in range(50):
        try:
            shutil.rmtree(folder, ignore_errors=True)
            shutil.copytree(backup / "scene", folder)
            break
        except OSError:
            time.sleep(0.2)
    shutil.rmtree(backup, ignore_errors=True)


def test_a_scene_opens_in_its_own_editor_and_is_not_added_to_the_level(game_level, physics_scene_restored):
    """OpenScene: its own session (type Scene, the scene's guid) next to the Level, with the scene's entities; the Level has not got the scene; it works under the Level's Game; edit, undo, redo, save,
    close and open again: the same content."""
    lv = game_level
    ed = lv.ed
    before = [s.name for s in ed.sessions()]
    scenes_of_level = lv.cmd("ListScenes")
    assert PHYSICS not in scenes_of_level
    s = _open(ed, PHYSICS, "Physics")
    try:
        sessions = ed.sessions()
        mine = next(x for x in sessions if x.name == "Physics")
        assert int(mine.guid, 16) == int(PHYSICS, 16) and mine.name not in before and lv.name in [x.name for x in sessions]
        assert len(s.entities()) >= 1, "the entities of the scene load"
        assert not s.dirty() and PHYSICS not in lv.cmd("ListScenes"), "it is not part of the Level"
        assert "is already open" in ed.cmd(f"OpenScene -Scene {PHYSICS}"), "a second OpenScene of it says so"

        entity = "7E571234"
        s.ok(f"CreateEntity -Scene {PHYSICS} -Id {entity} -Folder 0")
        s.ok(f"AddComponent -Scene {PHYSICS} -Id {entity} -Component Transform")
        assert entity in s.entities() and s.dirty()
        s.cmd("Undo")
        s.cmd("Undo")
        assert entity not in s.entities() and not s.dirty(), "undone back to what was saved: clean"
        s.cmd("Redo")
        s.cmd("Redo")
        assert entity in s.entities() and s.dirty()
        s.cmd("Undo")
        s.cmd("Undo")
        entity = "7E571236"                                      # (an id that was undone and made again in the same session is a different question)
        s.ok(f"CreateEntity -Scene {PHYSICS} -Id {entity} -Folder 0")
        s.ok(f"AddComponent -Scene {PHYSICS} -Id {entity} -Component Transform")
        assert "rror" not in s.cmd("Save", allow_disk=True) and not s.dirty()
        s.close()

        s = _open(ed, PHYSICS, "Physics")
        assert entity in s.entities(), "saved: the reopened scene has it"
        s.ok(f"DeleteEntity -Scene {PHYSICS} -Id {entity}")
        assert "rror" not in s.cmd("Save", allow_disk=True)
    finally:
        s.close()


def test_a_scene_opens_from_the_resource_editor_command_too(game_level):
    """What a double click on a Scene in the Asset Browser does (the editor registered for the Scene type): OpenResourceEditor makes the same Scene Editor, CloseResourceEditor closes it."""
    ed = game_level.ed
    s = _open(ed, PHYSICS, "Physics")
    scene_type = next(x for x in ed.sessions() if x.name == "Physics").type_guid
    s.close()
    lib = ed.libraries()[0][0]
    try:
        assert ed.cmd(f"OpenResourceEditor -Asset {PHYSICS}{scene_type} -Library {lib}", timeout=240) == ""
        ed.wait_for("GetPlayState", r"Building=false", timeout=240)
        assert "Physics" in [x.name for x in ed.sessions()] and len(s.entities()) >= 1
        assert ed.cmd(f"CloseResourceEditor -Asset {PHYSICS}{scene_type}") == ""
        deadline = time.monotonic() + 15
        while "Physics" in [x.name for x in ed.sessions()] and time.monotonic() < deadline:
            time.sleep(0.2)
        assert "Physics" not in [x.name for x in ed.sessions()]
    finally:
        s.close()


def test_a_scene_that_a_level_has_open_is_not_opened_again(game_level):
    """One writer per Scene: the Pitch is part of the open Soccer Level: OpenScene says where it is open, opens nothing, and leaves the Level's selection as it was."""
    lv = game_level
    ed = lv.ed
    sessions = [x.name for x in ed.sessions()]
    selected = re.search(r"SelectedEntity=(\S+)", lv.cmd("DescribeLevel"))[1]
    reply = ed.cmd(f"OpenScene -Scene {PITCH}", timeout=60)
    assert "already open in" in reply and lv.name in reply, reply
    assert [x.name for x in ed.sessions()] == sessions, "no second copy of the scene"
    assert re.search(r"SelectedEntity=(\S+)", lv.cmd("DescribeLevel"))[1] == selected


def test_a_click_is_no_change_and_a_clean_scene_editor_closes_without_asking(game_level):
    """A selection is an undo step but not an unsaved change; the editor of a scene nobody changed closes without the question, one that was changed asks (once) and Don't Save leaves the file."""
    ed = game_level.ed
    s = _open(ed, PHYSICS, "Physics")
    try:
        entity = next(iter(s.entities()))
        s.ok(f"Select -Scene {PHYSICS} -Id {entity}")
        assert not s.dirty(), "a click changes nothing of the scene"
        s.ok(f"CreateEntity -Scene {PHYSICS} -Id 7E571235 -Folder 0")
        assert s.dirty() and "unsaved" in s.cmd("Close").lower(), "a changed scene asks before it closes"
        assert "Physics" in [x.name for x in ed.sessions()]
    finally:
        s.close()                                                    # Close -Save 0: nothing written
    s = _open(ed, PHYSICS, "Physics")
    try:
        assert "7E571235" not in s.entities(), "Don't Save left the file as it was"
        assert "unsaved" not in s.cmd("Close").lower(), "a clean editor closes without asking"
        deadline = time.monotonic() + 15
        while "Physics" in [x.name for x in ed.sessions()] and time.monotonic() < deadline:
            time.sleep(0.2)
        assert "Physics" not in [x.name for x in ed.sessions()]
    finally:
        s.close()


def test_a_scene_that_did_not_load_whole_is_never_written(game_level, physics_scene_restored):
    """A Scene one of whose entities cannot be loaded (a component no module registers: its module is not in the Game) is open in its editor, and another of its entities is changed. Save, Close -Save 1
    and Save All refuse it - nothing is written (the entities that loaded may have lost their references to the one that did not) - say what is missing and how to fix it, and the editor stays unsaved."""
    ed = game_level.ed
    folder = _guid_folder("Scene", PHYSICS)
    entity = folder / "entity_db" / "01" / "01" / "00000101.entity"
    text = entity.read_bytes().decode()
    assert "#296EEAAEE0EF730" in text
    entity.write_bytes(text.replace("#296EEAAEE0EF730", "#DEADBEEF00000001", 1).encode())
    files = {str(f.relative_to(folder)): f.read_bytes() for f in sorted(folder.rglob("*")) if f.is_file()}
    s = _open(ed, PHYSICS, "Physics")
    try:
        assert "00000101" not in s.entities(), "that entity did not load"
        s.ok(f"CreateEntity -Scene {PHYSICS} -Id 7E571237 -Folder 0")
        assert s.dirty()
        for line, kept in (("Save", "it stays unsaved"), ("Close -Save 1", "stays open")):
            reply = s.cmd(line, allow_disk=True)
            assert "was not saved" in reply and "could not be loaded" in reply and "Give it a Game that lists that module" in reply and kept in reply, reply
            assert "Physics" in [x.name for x in ed.sessions()] and s.dirty(), line
        ed.cmd("SaveAll", allow_disk=True)
        assert s.dirty()
        now = {str(f.relative_to(folder)): f.read_bytes() for f in sorted(folder.rglob("*")) if f.is_file()}
        assert now == files, "nothing of the scene was written"
    finally:
        s.close()


def test_a_scene_that_needs_a_game_opens_under_the_only_game_of_the_project(level):
    """The Level of this test names no Game, and the Pitch needs the module of the Soccer Game: a Scene names none, so its editor works under the Game of the active Level, else the project's only Game, in memory
    (the pitch loads whole, with its 72 entities, and nothing was written into any file)."""
    ed = level.ed
    s = _open(ed, PITCH, "Pitch")
    try:
        assert len(s.entities()) >= 60, "the Soccer module's components load: a Game was found"
    finally:
        s.close()
