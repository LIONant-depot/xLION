"""The Prefab Editor (documentation/Editors/prefabs_plan.md, phase 5): a prefab opens in its own editor, which is the Level editor with the prefab as its document.

A prefab is stored as a scene, so the editor opens it as a scene of its own guid: its entities are ordinary live ones and the commands of the scene editor edit them (Name\\CreateEntity, Name\\SetProperty,
Undo, Save ...). What these tests hold:

  * a prefab opens next to the Level (OpenPrefab), listed as a session of the Prefab type, with the entities of the prefab; edits are undoable, make it dirty, Save writes the prefab (the same ids)
    and a Level that places the prefab afterwards has the change;
  * a prefab keeps one root and references only its own entities: a document that breaks that is not saved (and stays dirty);
  * Play: the prefab plays by itself (a collider gets its body), Stop puts it back;
  * context scenes: brought in to test against, they play, are never picked, edited or saved, and are no part of the prefab;
  * one writer per prefab: Apply Overrides from a Level into a prefab that is open in a Prefab Editor does not write the file - it is an undo step of that editor;
  * the Game a prefab plays with (the one of the Level it was made in), SetPrefabGame (refuses a Game that lacks a module), and every save keeps it;
  * every example prefab opens and saves back the same entity files; a prefab in the old format is refused until UpgradeProject.
"""
import re
import secrets
import shutil
import time
from pathlib import Path

import pytest
from harness import quote
from test_prefabs import (PREFAB_TYPE, _component_guid, _guid_folder, _instantiate, _new_asset, _old_prefab_copy, level_files_restored, restoring_level_files, PREFAB_V1)      # noqa: F401  (a fixture and the helpers of the prefab tests)


class PrefabEditor:
    """A Prefab Editor session: the commands go to it as Name\\Command, the document is the scene of the prefab's guid."""

    def __init__(self, ed, guid: str, name: str) -> None:
        self.ed, self.guid, self.name = ed, guid, name

    def cmd(self, line: str, **kw) -> str:
        return self.ed.cmd(f"{self.name}\\{line}", **kw)

    def ok(self, line: str, **kw) -> None:
        self.ed.ok(f"{self.name}\\{line}", **kw)

    @property
    def scene(self) -> str:
        return self.guid

    def entities(self) -> dict:
        return self.ed.entities(self.name, self.guid)

    def describe(self, entity: str) -> str:
        return self.ed.describe(self.name, self.guid, entity)

    def dirty(self) -> bool:
        return next(s.dirty for s in self.ed.sessions() if s.name == self.name)

    def info(self) -> dict:
        return dict(re.findall(r"^(\w+)=(.*)$", self.cmd("DescribePrefab"), re.M))

    def root(self) -> str:
        return self.info()["Root"]

    def x(self, entity: str) -> float:
        return float(re.search(r"Transform/Position/X = (\S+)", self.describe(entity))[1])

    def set_x(self, entity: str, value: str) -> None:
        m = re.search(r"Transform/Position/X = (\S+)\s+\(TypeGuid (\w+)\)", self.describe(entity))
        self.ok(f"SetProperty -Scene {self.guid} -Id {entity} -Component {_component_guid(self, 'Transform')} -Path {quote('Transform/Position/X')} -TypeGuid {m[2]} -Before {quote(m[1])} -After {quote(value)}")

    def add_child(self, parent: str, ids) -> str:
        child = f"7E58{next(ids):04X}"
        self.ok(f"CreateEntity -Scene {self.guid} -Id {child} -Folder 0 -Parent {parent}")
        self.ok(f"AddComponent -Scene {self.guid} -Id {child} -Component {_component_guid(self, 'Transform')}")
        return child

    def close(self) -> None:
        if self.name not in [s.name for s in self.ed.sessions()]:
            return
        self.ed.cmd(f"{self.name}\\Close -Save 0")
        deadline = time.monotonic() + 15
        while self.name in [s.name for s in self.ed.sessions()] and time.monotonic() < deadline:
            time.sleep(0.2)


def _make(level, *, children: int = 0, parts=("Transform",)) -> tuple:
    """A new prefab (its root named so that its editor has a name of its own: the name of the Prefab asset); returns (prefab guid, name)."""
    name = "PfEd" + secrets.token_hex(3).upper()
    root = level.new_entity()
    for part in parts:
        level.ok(f"AddComponent -Scene {level.scene} -Id {root} -Component {_component_guid(level, part)}")
    level.ok(f"RenameEntity -Scene {level.scene} -Id {root} -Name {name}")
    for _ in range(children):
        child = f"7E57{next(level._ids):04X}"
        level.ok(f"CreateEntity -Scene {level.scene} -Id {child} -Folder 0 -Parent {root}")
        level.ok(f"AddComponent -Scene {level.scene} -Id {child} -Component {_component_guid(level, 'Transform')}")
    asset, lib, parent = _new_asset(level)
    level.ok(f"MakePrefab -Scene {level.scene} -Id {root} -Library {lib} -Asset {asset} -Parent {parent}", allow_disk=True)
    return asset[:16], name


@pytest.fixture
def opened(editor):
    """open(prefab, name) -> PrefabEditor; whatever a test opened is closed when it ends. A test asks for it after its Level fixture, so that it is closed before the Level."""
    made = []

    def open_(prefab: str, name: str) -> PrefabEditor:
        reply = editor.cmd(f"OpenPrefab -Prefab {prefab}", timeout=120)
        assert reply.startswith("Opened Prefab"), reply
        editor.wait_for("GetPlayState", r"Building=false", timeout=240)
        made.append(PrefabEditor(editor, prefab, name))
        return made[-1]

    yield open_
    for p in reversed(made):
        if editor.alive():
            if "Playing" in p.cmd("GetPlayState") or "Paused" in p.cmd("GetPlayState"):
                p.cmd("Stop -Keep false")
                editor.wait_for(f"{p.name}\\GetPlayState", r"PlayState=Stopped", timeout=60)
            p.close()


def _prefab_files(prefab: str) -> dict:
    """{relative path: bytes} of the prefab's folder."""
    folder = _guid_folder("Prefab", prefab)
    return {str(f.relative_to(folder)): f.read_bytes() for f in sorted(folder.rglob("*")) if f.is_file()}


def _entity_files(prefab: str) -> dict:
    return {k: v for k, v in _prefab_files(prefab).items() if k.endswith(".entity")}


def _descriptor(prefab: str) -> str:
    return (_guid_folder("Prefab", prefab) / "Descriptor.txt").read_text(errors="replace")


# ---- opening, editing, saving ---------------------------------------------------------------------------------------------------------------------------------------------------------------

def test_a_prefab_opens_in_its_own_editor_next_to_the_level(level, opened):
    """OpenPrefab: its own session (type Prefab, the prefab's guid), with the prefab's entities; the Level is still open; opening it again says so."""
    prefab, name = _make(level, children=1)
    p = opened(prefab, name)

    sessions = {s.name: s for s in level.ed.sessions()}
    assert level.name in sessions and name in sessions, f"the Level and the Prefab are both open: {list(sessions)}"
    assert sessions[name].type_guid == PREFAB_TYPE and int(sessions[name].guid, 16) == int(prefab, 16)
    assert not p.dirty(), "a prefab that was just opened has nothing unsaved"
    assert len(p.entities()) == 2, "the prefab's root and its child"

    info = p.info()
    assert info["Entities"] == "2" and info["Root"] in p.entities() and int(info["Prefab"], 16) == int(prefab, 16)
    assert info["Scene"] == prefab, "the document is the scene of the prefab's guid"
    assert "is already open" in level.ed.cmd(f"OpenPrefab -Prefab {prefab}")
    assert len(level.ed.sessions()) == 2

    # the prefab row of the tree: selecting it is what the Inspector shows the prefab's own properties for
    assert info["Selected"] == "false"
    p.ok("SelectLevel")
    assert p.info()["Selected"] == "true"
    p.cmd("Undo")
    assert p.info()["Selected"] == "false"


def test_a_prefab_opens_from_the_resource_editor_command_too(level, opened):
    """What a double click on a Prefab in the Asset Browser does (the editor registered for the Prefab type): OpenResourceEditor makes the same Prefab Editor, CloseResourceEditor closes it."""
    prefab, name = _make(level, children=1)
    lib = level.ed.libraries()[0][0]
    p = PrefabEditor(level.ed, prefab, name)
    try:
        assert level.ed.cmd(f"OpenResourceEditor -Asset {prefab}{PREFAB_TYPE} -Library {lib}", timeout=120) == ""
        level.ed.wait_for("GetPlayState", r"Building=false", timeout=240)
        assert name in [s.name for s in level.ed.sessions()] and len(p.entities()) == 2
        assert level.ed.cmd(f"CloseResourceEditor -Asset {prefab}{PREFAB_TYPE}") == ""
        deadline = time.monotonic() + 15
        while name in [s.name for s in level.ed.sessions()] and time.monotonic() < deadline:
            time.sleep(0.2)
        assert name not in [s.name for s in level.ed.sessions()]
    finally:
        p.close()


def test_edit_undo_save_and_reopen_a_prefab(level, opened):
    """An edit makes the editor dirty and Undo/Redo move it; Save writes the prefab (the ids it had, the new child), clean again; reopened it is what was saved, and a new instance of the prefab has it."""
    prefab, name = _make(level, children=1)
    p = opened(prefab, name)
    root = p.root()
    base = p.x(root)

    p.set_x(root, "11.000000")
    assert p.x(root) == 11.0 and p.dirty()
    p.cmd("Undo")
    assert p.x(root) == base and not p.dirty(), "undone back to the saved state: not dirty"
    p.cmd("Redo")
    assert p.x(root) == 11.0 and p.dirty()

    before_ids = set(p.entities())
    child = p.add_child(root, level._ids)
    p.set_x(child, "5.000000")
    reply = p.cmd("Save", allow_disk=True)
    assert reply == "Saved", reply
    assert not p.dirty()
    ids = set(p.entities())
    assert ids == before_ids | {child}
    assert len(_entity_files(prefab)) == 3, "one file per entity"
    assert root.lstrip("0").upper() in _descriptor(prefab).upper() or str(int(root, 16)) in _descriptor(prefab), "the descriptor names the root"

    p.close()
    p = opened(prefab, name)
    assert set(p.entities()) == ids, "the same ids after the prefab was saved and opened again"
    assert p.x(root) == 11.0 and p.x(child) == 5.0

    before = set(level.entities())
    placed = _instantiate(level, prefab)
    members = set(level.entities()) - before - {placed}
    assert len(members) == 2, "an instance of the saved prefab has its three entities"
    assert level.describe(placed).count("Transform/Position/X = 11") == 1


def test_a_prefab_with_two_roots_is_not_saved_and_stays_unsaved(level, opened):
    """A prefab has exactly one root (the entity with no parent): a stray entity makes the save refuse, nothing is written, and the editor stays dirty. Undo takes the stray away, and the save works."""
    prefab, name = _make(level, children=1)
    p = opened(prefab, name)
    files = _prefab_files(prefab)

    stray = f"7E58{next(level._ids):04X}"
    p.ok(f"CreateEntity -Scene {p.guid} -Id {stray} -Folder 0")
    reply = p.cmd("Save", allow_disk=True)
    assert "not saved" in reply and p.dirty(), reply
    assert _prefab_files(prefab) == files, "nothing was written"

    p.cmd("Undo")
    assert "Saved" == p.cmd("Save", allow_disk=True)
    assert not p.dirty()


def test_a_prefab_cannot_hold_itself_or_folders(level, opened):
    prefab, name = _make(level)
    p = opened(prefab, name)
    reply = p.cmd(f"InstantiatePrefab -Scene {p.guid} -Id {7:08X} -Prefab {prefab} -Folder 0")
    assert "cannot hold an instance of itself" in reply, reply
    assert "no folders" in p.cmd(f"CreateFolder -Scene {p.guid} -Id 00000042 -Parent 0 -Name Nope")


def test_closing_a_dirty_prefab_editor_asks_and_discarding_leaves_the_file(level, opened):
    prefab, name = _make(level)
    p = opened(prefab, name)
    files = _prefab_files(prefab)
    p.set_x(p.root(), "3.000000")
    assert "unsaved changes" in p.cmd("Close")
    assert p.name in [s.name for s in level.ed.sessions()]
    p.close()
    assert p.name not in [s.name for s in level.ed.sessions()]
    assert _prefab_files(prefab) == files


# ---- Play -----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

def test_a_prefab_plays_by_itself_and_a_collider_gets_its_body(level, opened, level_files_restored):
    """Play in a Prefab Editor builds the world from the saved prefab, builders on: its collider has a physics body; Stop puts the prefab back as it was."""
    prefab, name = _make(level, parts=("Transform", "Physics", "PhysicsBodyProperties", "PhysicsColliderBox", "PhysicsDynamics"))
    p = opened(prefab, name)
    root = p.root()
    assert "rror" not in level.cmd("Save", allow_disk=True)          # Play is refused while a session has unsaved edits: the Level (it holds the entity the prefab was made from) is saved first
    assert "rror" not in p.cmd("Play", allow_disk=True)
    level.ed.wait_for(f"{p.name}\\GetPlayState", r"PlayState=Playing", timeout=120)
    assert float(re.search(r"Physics/BodyGeneration = (\S+)", p.describe(root))[1]) != 0, "the collider of the prefab has its body"
    assert level.ed.play_state() != "Stopped" or "Playing" in p.cmd("GetPlayState")

    p.cmd("Stop -Keep false")
    level.ed.wait_for(f"{p.name}\\GetPlayState", r"PlayState=Stopped", timeout=60)
    assert root in p.entities() and not p.dirty()


# ---- context scenes -------------------------------------------------------------------------------------------------------------------------------------------------------------------------

def test_a_context_scene_plays_with_the_prefab_and_is_never_picked_edited_or_saved(level, opened, level_files_restored):
    prefab, name = _make(level, children=1)
    p = opened(prefab, name)
    scene = level.scene
    assert p.cmd("ListContextScenes").startswith("(no context")

    reply = p.cmd(f"AddContextScene -Scene {scene}")
    assert "ok" in reply, reply
    assert "already" in p.cmd(f"AddContextScene -Scene {scene}")
    listing = p.cmd("ListContextScenes")
    assert scene in listing and not re.search(r"entities=0\b", listing), listing
    assert p.info()["ContextScenes"] != "(none)"

    # the scene's entities are in this world (they play), and are no part of the prefab
    context_entities = p.ed.entities(p.name, scene)
    assert context_entities and set(context_entities).isdisjoint(p.entities())
    entity = next(iter(context_entities))
    assert "Transform" in p.ed.describe(p.name, scene, entity) or "[" in p.ed.describe(p.name, scene, entity)

    # not edited, not picked
    assert "refused" in p.cmd(f"Select -Scene {scene} -Id {entity}")
    assert "refused" in p.cmd(f"DeleteEntity -Scene {scene} -Id {entity}")
    assert entity in p.ed.entities(p.name, scene)

    # not saved: the prefab's files hold the prefab and nothing of the scene
    p.set_x(p.root(), "2.000000")
    assert p.cmd("Save", allow_disk=True) == "Saved"
    assert len(_entity_files(prefab)) == 2
    assert not set(re.findall(r"([0-9A-F]{8,16})\.entity", " ".join(_prefab_files(prefab)))) & set(context_entities)

    # it plays with the prefab, and Stop brings both back
    assert "rror" not in level.cmd("Save", allow_disk=True)
    assert "rror" not in p.cmd("Play", allow_disk=True)
    level.ed.wait_for(f"{p.name}\\GetPlayState", r"PlayState=Playing", timeout=120)
    assert entity in p.ed.entities(p.name, scene), "the context scene is in the world that plays"
    p.cmd("Stop -Keep false")
    level.ed.wait_for(f"{p.name}\\GetPlayState", r"PlayState=Stopped", timeout=60)
    assert entity in p.ed.entities(p.name, scene) and not p.dirty()

    assert "ok" in p.cmd(f"RemoveContextScene -Scene {scene}")
    assert p.cmd("ListContextScenes").startswith("(no context")
    assert "not a context scene" in p.cmd(f"RemoveContextScene -Scene {scene}")


def test_a_prefab_cannot_reference_an_entity_of_a_context_scene(level, opened):
    prefab, name = _make(level, children=1)
    p = opened(prefab, name)
    scene = level.scene
    assert "ok" in p.cmd(f"AddContextScene -Scene {scene}")
    target = next(iter(p.ed.entities(p.name, scene)))
    holder = p.root()
    p.ok(f"AddComponent -Scene {p.guid} -Id {holder} -Component {_component_guid(p, 'EntityReference')}")
    files = _prefab_files(prefab)
    p.ok(f"SetEntityReference -Scene {p.guid} -Id {holder} -Component {_component_guid(p, 'EntityReference')} -Path EntityReference/Target -AfterScene {scene} -AfterId {target}")

    reply = p.cmd("Save", allow_disk=True)
    assert "not saved" in reply and p.dirty(), reply
    assert _prefab_files(prefab) == files, "nothing was written"
    p.cmd("Undo")
    assert p.cmd("Save", allow_disk=True) == "Saved"


# ---- one writer per prefab ------------------------------------------------------------------------------------------------------------------------------------------------------------------

def test_apply_overrides_into_an_open_prefab_editor_is_an_undo_step_there(level, opened, level_files_restored):
    """The Prefab Editor is the one writer of the prefab: an instance in a Level applying its override does not write the file; the editor takes it as a change of its document (dirty, undoable),
    and Save writes it."""
    prefab, name = _make(level, children=1)
    p = opened(prefab, name)
    root = p.root()
    base = p.x(root)
    files = _prefab_files(prefab)

    instance = _instantiate(level, prefab)
    m = re.search(r"Transform/Position/X = (\S+)\s+\(TypeGuid (\w+)\)", level.describe(instance))
    level.ok(f"SetProperty -Scene {level.scene} -Id {instance} -Component {_component_guid(level, 'Transform')} -Path {quote('Transform/Position/X')} -TypeGuid {m[2]} -Before {quote(m[1])} -After {quote('7.500000')}")
    level.ok(f"ApplyOverrides -Scene {level.scene} -Id {instance}", allow_disk=True)

    assert _prefab_files(prefab) == files, "the file was not written behind the editor's back"
    assert p.x(root) == 7.5 and p.dirty(), "the editor has the change, as an unsaved step"
    assert set(p.entities()) >= {root}, "the same entities, with the same ids"

    p.cmd("Undo")
    assert p.x(root) == base and not p.dirty(), "undone in the editor"
    p.cmd("Redo")
    assert p.x(root) == 7.5 and p.dirty()

    level.cmd("Undo")                       # the Level's own undo of the Apply: the prefab goes back, and the editor hears it as one more step
    assert _prefab_files(prefab) == files, "still no file written"
    assert p.x(root) == base and p.dirty()
    p.cmd("Undo")
    assert p.x(root) == 7.5
    p.cmd("Undo")
    assert p.x(root) == base and not p.dirty(), "both steps undone: back to what the file holds"
    p.cmd("Redo"); p.cmd("Redo")
    assert p.x(root) == base
    level.cmd("Redo")                       # the Apply again
    assert p.x(root) == 7.5 and p.dirty()
    assert p.cmd("Save", allow_disk=True) == "Saved"
    assert _prefab_files(prefab) != files and not p.dirty()
    p.close()
    p = opened(prefab, name)
    assert p.x(p.root()) == 7.5, "saved by the editor"


def test_apply_overrides_with_no_editor_open_still_writes_the_prefab(level, level_files_restored):
    prefab, _ = _make(level)
    files = _prefab_files(prefab)
    instance = _instantiate(level, prefab)
    m = re.search(r"Transform/Position/X = (\S+)\s+\(TypeGuid (\w+)\)", level.describe(instance))
    level.ok(f"SetProperty -Scene {level.scene} -Id {instance} -Component {_component_guid(level, 'Transform')} -Path {quote('Transform/Position/X')} -TypeGuid {m[2]} -Before {quote(m[1])} -After {quote('4.500000')}")
    level.ok(f"ApplyOverrides -Scene {level.scene} -Id {instance}", allow_disk=True)
    assert _prefab_files(prefab) != files


def test_close_with_save_of_a_prefab_that_cannot_be_saved_stays_open(level, opened):
    """Close -Save 1 on a prefab that breaks a rule of a prefab (two roots): nothing is written, so it must not close saying it saved - it stays open and unsaved, and says why."""
    prefab, name = _make(level, children=1)
    p = opened(prefab, name)
    files = _prefab_files(prefab)
    stray = f"7E58{next(level._ids):04X}"
    p.ok(f"CreateEntity -Scene {p.guid} -Id {stray} -Folder 0")
    reply = p.cmd("Close -Save 1", allow_disk=True)
    assert "not saved" in reply and "Saved and closed" not in reply, reply
    assert p.name in [s.name for s in level.ed.sessions()] and p.dirty(), "still open, still unsaved"
    assert _prefab_files(prefab) == files
    p.close()


def test_an_apply_the_editor_cannot_take_as_a_step_is_written_to_the_file(level, opened, level_files_restored):
    """The editor's document breaks a rule (a stray root), so it has no snapshot to undo to and cannot take Apply Overrides as an undoable step: the file takes the change (the file is the truth),
    nothing is lost, the editor keeps its own unsaved edit and stays unsaved whatever is undone - never clean while different from the file."""
    prefab, name = _make(level, children=1)
    p = opened(prefab, name)
    root = p.root()
    base = p.x(root)
    files = _prefab_files(prefab)
    stray = f"7E58{next(level._ids):04X}"
    p.ok(f"CreateEntity -Scene {p.guid} -Id {stray} -Folder 0")

    instance = _instantiate(level, prefab)
    m = re.search(r"Transform/Position/X = (\S+)\s+\(TypeGuid (\w+)\)", level.describe(instance))
    level.ok(f"SetProperty -Scene {level.scene} -Id {instance} -Component {_component_guid(level, 'Transform')} -Path {quote('Transform/Position/X')} -TypeGuid {m[2]} -Before {quote(m[1])} -After {quote('7.500000')}")
    level.ok(f"ApplyOverrides -Scene {level.scene} -Id {instance}", allow_disk=True)

    assert _prefab_files(prefab) != files, "the Apply was written to the prefab's file: nobody lost it"
    assert p.dirty() and p.x(root) == base, "the editor keeps its own edit (the stray root) and does not pretend to have the change"
    p.cmd("Undo")                                    # the stray root goes
    assert p.dirty(), "undone back to where it was clean, yet it is not the file: it stays unsaved"
    p.close()
    p = opened(prefab, name)
    assert p.x(p.root()) == 7.5, "the file has what the Apply wrote"


# ---- the Game a prefab plays with --------------------------------------------------------------------------------------------------------------------------------------------------------------

def test_a_prefab_made_in_a_level_plays_with_the_game_of_that_level(game_level):
    """The Soccer level names a Game: a prefab made from it names the same one (D2), SetPrefabGame changes it (undoable), and a Game that lacks what the prefab needs is refused."""
    lv = game_level
    ed = lv.ed
    level_game = re.search(r"^Game=(\S+)", ed.cmd(f"GetLevelGame -Level {lv.guid}"), re.M)[1]
    prefab, name = _make(lv)
    got = ed.cmd(f"GetPrefabGame -Prefab {prefab}")
    assert re.search(r"^Game=(\S+)", got, re.M)[1] == level_game and "Source=set" in got, got

    assert ed.cmd(f"SetPrefabGame -Prefab {prefab}", allow_disk=True) == ""
    assert "Source=none" in ed.cmd(f"GetPrefabGame -Prefab {prefab}")
    assert ed.cmd(f"SetPrefabGame -Prefab {prefab} -Game {level_game}", allow_disk=True) == ""
    assert re.search(r"^Game=(\S+)", ed.cmd(f"GetPrefabGame -Prefab {prefab}"), re.M)[1] == level_game
    assert "is not in the project" in ed.cmd("GetPrefabGame -Prefab 0000000000000001")
    assert "not a Game asset guid" in ed.cmd(f"SetPrefabGame -Prefab {prefab} -Game {'0' * 16}{PREFAB_TYPE}", allow_disk=True)


def test_every_save_of_a_prefab_keeps_its_game(game_level, opened):
    lv = game_level
    prefab, name = _make(lv)
    game = re.search(r"^Game=(\S+)", lv.ed.cmd(f"GetPrefabGame -Prefab {prefab}"), re.M)[1]
    p = opened(prefab, name)
    assert p.info()["Game"] == game
    p.set_x(p.root(), "1.000000")
    assert p.cmd("Save", allow_disk=True) == "Saved"
    assert re.search(r"^Game=(\S+)", lv.ed.cmd(f"GetPrefabGame -Prefab {prefab}"), re.M)[1] == game, "a save of the document keeps the Game"
    instance = _instantiate(lv, prefab)
    lv.ok(f"ApplyOverrides -Scene {lv.scene} -Id {instance}", allow_disk=True)
    assert re.search(r"^Game=(\S+)", lv.ed.cmd(f"GetPrefabGame -Prefab {prefab}"), re.M)[1] == game, "and so does an Apply Overrides from a Level"


def test_a_game_module_reload_keeps_the_prefab_document_and_its_context(editor, game_level, game_level_files_restored, opened):
    """Play after the game module's source changed rebuilds Game.dll and puts every world back around the swap: the prefab (a scene that is the document of its editor, with its own folder) and the context
    scene come back as they were, and a save afterwards still writes the prefab's folder - not a scene's."""
    import os
    from test_game_module_reload import GAME_SOURCE
    lv = game_level
    prefab, name = _make(lv, children=1)
    assert "rror" not in lv.cmd("Save", allow_disk=True)             # Play is refused while a session has unsaved edits (and the context scene is read from what is saved: the Level goes first)
    p = opened(prefab, name)
    assert "ok" in p.cmd(f"AddContextScene -Scene {lv.scene}")
    ids, context = set(p.entities()), set(p.ed.entities(p.name, lv.scene))
    p.set_x(p.root(), "9.000000")
    assert p.cmd("Save", allow_disk=True) == "Saved"

    os.utime(GAME_SOURCE)
    assert p.cmd("Play", allow_disk=True).startswith("Play requested")
    editor.wait_for(f"{p.name}\\GetPlayState", r"PlayState=Playing", timeout=300)           # includes the module rebuild
    assert set(p.entities()) == ids and set(p.ed.entities(p.name, lv.scene)) == context
    assert p.x(p.root()) == 9.0 and p.info()["ContextScenes"] != "(none)"
    p.cmd("Stop -Keep false")
    editor.wait_for(f"{p.name}\\GetPlayState", r"PlayState=Stopped", timeout=60)
    assert set(p.entities()) == ids and not p.dirty()

    p.set_x(p.root(), "4.000000")
    assert p.cmd("Save", allow_disk=True) == "Saved"
    assert not _guid_folder("Scene", prefab).exists(), "the prefab is saved as a prefab: no scene folder of its guid"
    p.close()
    p = opened(prefab, name)
    assert p.x(p.root()) == 4.0, "what the editor saved after the reload"


@pytest.fixture
def game_level_files_restored(game_level):
    """The Soccer Level and its Scenes put back as they were when the test ends (a test that saves it writes entities the next test's 7E57xxxx ids would collide with)."""
    yield from restoring_level_files(game_level)


# ---- the prefabs that exist ----------------------------------------------------------------------------------------------------------------------------------------------------------------------

def _example_prefabs() -> list:
    return sorted(p.name for p in PREFAB_V1.iterdir() if p.is_dir())


def test_every_example_prefab_opens_and_saves_back_the_same_entities(game_level, opened):
    """The example project's prefabs, opened in a Prefab Editor under the Soccer Game and saved without a change: their entity files are the ones they were (the document reads and writes what the
    prefab manager does), and what could not be read is kept, not lost. 66879B27D9D067FB (a component no module registers) does not open, as it does not load anywhere."""
    lv = game_level
    ed = lv.ed
    game = re.search(r"^Game=(\S+)", ed.cmd(f"GetLevelGame -Level {lv.guid}"), re.M)[1]
    opened_count = 0
    for prefab in _example_prefabs():
        files = _entity_files(prefab)
        if prefab == "66879B27D9D067FB":                # the one nobody can read: still in the old format, and it names a component no module registers
            assert "old format" in ed.cmd(f"SetPrefabGame -Prefab {prefab} -Game {game}", allow_disk=True)
            assert "failed" in ed.cmd(f"OpenPrefab -Prefab {prefab}", timeout=120)
            continue
        assert ed.cmd(f"SetPrefabGame -Prefab {prefab} -Game {game}", allow_disk=True) == "", prefab
        reply = ed.cmd(f"OpenPrefab -Prefab {prefab}", timeout=120)
        assert reply.startswith("Opened Prefab"), f"{prefab}: {reply}"
        name = next(s.name for s in ed.sessions() if s.type_guid == PREFAB_TYPE and int(s.guid, 16) == int(prefab, 16))
        p = PrefabEditor(ed, prefab, name)
        try:
            ed.wait_for("GetPlayState", r"Building=false", timeout=240)
            assert len(p.entities()) >= 1, prefab
            assert p.cmd("Save", allow_disk=True) == "Saved", prefab
            assert _entity_files(prefab) == files, f"{prefab}: the saved entity files differ from the ones that were there"
            opened_count += 1
        finally:
            p.close()
    assert opened_count == len(_example_prefabs()) - 1, "every example prefab but Shadow"


def test_a_prefab_in_the_old_format_is_refused_until_it_is_converted(level):
    guid, folder = _old_prefab_copy(PREFAB_V1 / next(n for n in _example_prefabs() if n != "66879B27D9D067FB"))
    try:
        reply = level.ed.cmd(f"OpenPrefab -Prefab {guid}", timeout=120)
        assert "failed to open" in reply and "old format" in reply and "UpgradeProject" in reply, reply
        assert guid not in [s.guid.lstrip("0") for s in level.ed.sessions()]
    finally:
        shutil.rmtree(folder, ignore_errors=True)              # the copy is no asset: the project guard does not remove it
        for empty in (folder.parent, folder.parent.parent):
            try:
                empty.rmdir()                                    # only when nothing else is in it
            except OSError:
                pass


# ---- nesting ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

def test_a_prefab_that_holds_an_instance_opens_with_its_members_and_saves_the_recipe(level, opened):
    """A prefab holding an instance of another (made with InstantiatePrefab -Parent, then MakePrefab): the editor shows the nested members (derived ids), an override inside the nested instance saves
    as the recipe of the nested instance (not as files of its members) and survives closing and opening."""
    inner, _ = _make(level, children=1)
    outer_root = level.new_entity()
    level.ok(f"AddComponent -Scene {level.scene} -Id {outer_root} -Component {_component_guid(level, 'Transform')}")
    name = "PfEd" + secrets.token_hex(3).upper()
    level.ok(f"RenameEntity -Scene {level.scene} -Id {outer_root} -Name {name}")
    nested = f"7E57{next(level._ids):04X}"
    level.ok(f"InstantiatePrefab -Scene {level.scene} -Id {nested} -Prefab {inner} -Folder 0 -Parent {outer_root}")
    asset, lib, parent = _new_asset(level)
    level.ok(f"MakePrefab -Scene {level.scene} -Id {outer_root} -Library {lib} -Asset {asset} -Parent {parent}", allow_disk=True)
    outer = asset[:16]

    p = opened(outer, name)
    ids = p.entities()
    assert len(ids) == 3, f"the outer root, the nested instance and the nested instance's child: {ids}"
    assert sum(1 for e in ids if len(e) == 16) == 1, "the nested member has a derived id (16 digits)"
    member = next(e for e in ids if len(e) == 16)
    assert len(_entity_files(outer)) == 2, "the prefab writes the root and the nested instance: not the member"

    p.set_x(member, "21.000000")
    assert p.cmd("Save", allow_disk=True) == "Saved"
    assert len(_entity_files(outer)) == 2, "still no file for the member after a save"
    p.close()
    p = opened(outer, name)
    assert member in p.entities() and p.x(member) == 21.0, "the override inside the nested instance survived"

    before = set(level.entities())
    placed = _instantiate(level, outer)
    values = sorted(level.describe(e).count("Transform/Position/X = 21") for e in set(level.entities()) - before - {placed})
    assert values and values[-1] == 1, "an instance of the outer prefab has the nested override"
