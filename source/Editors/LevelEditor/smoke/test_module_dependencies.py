"""Which script module defines a component, which modules a scene needs, and whether a Game can run it.

The Game.dll says where each of its components and systems is defined (the registration macros capture __FILE__) and the editor maps the file to its module. A scene's ComponentDeps.txt
records the module of each component it uses when it is saved. A Game is compatible with a scene when it lists every module the scene needs: a plain comparison of files, no DLL involved.
"""
import pathlib
import re

import pytest

from harness import REPO
from script_project import PROJECT, new_asset, remove_asset

MODULE_TYPE = "8D3968CB1287FA04"
GAME_TYPE = "A3F1D6C0452E9B17"
MODULE = "3849E1DE2402B1A5"
MODULE_ASSET = f"{MODULE}{MODULE_TYPE}"
SOCCER_LEVEL = "0166FAE5EB82F3F3"
PITCH = "5B388EFC2203EC6F"                                                       # the scene of the Soccer level
PITCH_DEPS = PROJECT / "Descriptors" / "Scene" / "6F" / "EC" / f"{PITCH}.desc" / "ComponentDeps.txt"
OTHER_SCENE_DEPS = PROJECT / "Descriptors" / "Scene" / "03" / "4F" / "5C0A11E7B2D34F03.desc" / "ComponentDeps.txt"


def rows(reply: str) -> list:
    """The tab separated rows of a query reply, after its header line and its column names."""
    lines = [l for l in reply.splitlines() if "\t" in l]
    return [l.split("\t") for l in lines[1:]]


def deps(path) -> dict:
    """{component name: module (hex)} from a ComponentDeps.txt written with the Module column."""
    found = {}
    for m in re.finditer(r'#(\w+)\s+"([^"]+)"\s+#(\w+)', path.read_bytes().decode()):
        found[m[2]] = m[3]
    return found


def open_soccer(editor) -> None:
    editor.cmd("Close -Save 0")
    assert editor.cmd(f"OpenLevel -Level {SOCCER_LEVEL} -Save 0").startswith("Opened Level")
    editor.wait_for("GetPlayState", r"Building=false", timeout=240)             # the startup Game.dll check must settle


@pytest.fixture(scope="module")
def pitch_saved(editor):
    """The Soccer level opened with its game module loaded and saved: the scene's ComponentDeps.txt now names the module of each component. Put back afterwards."""
    original = PITCH_DEPS.read_bytes()
    open_soccer(editor)
    reply = editor.cmd("Save", allow_disk=True)
    assert "rror" not in reply, reply
    editor.cmd("Close -Save 0")
    yield
    PITCH_DEPS.write_bytes(original)


# ---- the map: which module defines each component and system -----------------------------------------------------------------------------------------------------------------------

@pytest.fixture
def soccer_open(editor):
    """The Soccer level open: the Game it names is loaded for it, and the registrations are the ones of that Game."""
    open_soccer(editor)
    yield
    editor.cmd("Close -Save 0")


def test_the_components_and_systems_of_the_game_dll_are_mapped_to_their_module(editor, soccer_open):
    reply = editor.cmd("ListModuleRegistrations")
    table = {r[2]: r for r in rows(reply) if r[0] in ("component", "system")}
    assert table["SoccerBall"][3] == MODULE_ASSET, "a component is in the module whose header defines it"
    assert table["SoccerBall"][4] == "soccer_components.h", "and the file is shown from the module's source_db"
    assert table["Soccer Ball"][0] == "system" and table["Soccer Ball"][3] == MODULE_ASSET and table["Soccer Ball"][4] == "soccer_ball_system.h"
    assert table["Transform"][3] == "-", "the engine's own components belong to no module"


def test_registrations_can_be_asked_for_one_module(editor, soccer_open):
    reply = editor.cmd(f"ListModuleRegistrations -Module {MODULE_ASSET}")
    found = rows(reply)
    assert found and all(r[3] == MODULE_ASSET for r in found), "only that module's types"
    assert {"SoccerBall", "SoccerPlayer"} <= {r[2] for r in found} and "Transform" not in {r[2] for r in found}
    assert "not a Script-Module" in editor.cmd(f"ListModuleRegistrations -Module 0000000000000001{GAME_TYPE}")


# ---- a scene that is saved names the module of each component -------------------------------------------------------------------------------------------------------------------------

def test_a_saved_scene_names_the_module_of_each_component(editor, pitch_saved):
    saved = deps(PITCH_DEPS)
    assert saved["SoccerBall"] == MODULE and saved["SoccerMatch"] == MODULE, "a component of a script module carries the module's guid"
    assert saved["Transform"] == "0" and saved["Entity"] == "0", "the engine's components belong to no module"


def test_the_modules_a_scene_needs_are_listed_with_their_components(editor, pitch_saved):
    reply = editor.cmd(f"ListSceneModules -Scene {PITCH}")
    found = {r[0]: r for r in rows(reply)}
    assert MODULE_ASSET in found and found[MODULE_ASSET][1] == "SoccerGame"
    assert "SoccerBall" in found[MODULE_ASSET][2] and "Transform" not in found[MODULE_ASSET][2]
    assert "unknown" not in found, "every component of a saved scene has a module (or none)"


def test_an_old_component_file_without_the_module_column_is_read_as_unknown(editor, pitch_saved):
    saved = PITCH_DEPS.read_bytes()
    try:
        old = re.sub(rb'(#\w+\s+"[^"]+")\s+#\w+', rb"\1", saved)                      # the file as it was before modules were tracked
        old = old.replace(b"Name:s                  }", b"Name:s }").replace(b"{ Guid:G             Name:s                   Module:G", b"{ Guid:G             Name:s")
        PITCH_DEPS.write_bytes(re.sub(rb"\{[^}]*\}", b"{ Guid:G             Name:s                  }", old, count=1))
        found = {r[0]: r for r in rows(editor.cmd(f"ListSceneModules -Scene {PITCH}"))}
        assert "unknown" in found and "SoccerBall" in found["unknown"][2], "an old file still reads: its components have no known module"
        assert "compatible" in editor.cmd(f"CheckGameCompatibility -Scene {PITCH}"), "and an unknown module never blocks a Game"
    finally:
        PITCH_DEPS.write_bytes(saved)


# ---- the compatibility check ---------------------------------------------------------------------------------------------------------------------------------------------------------

def test_the_project_game_can_run_the_scene_and_a_game_without_the_module_cannot(editor, pitch_saved):
    lib = editor.libraries()[0][0]
    empty = new_asset(editor, lib, GAME_TYPE, "Empty game")
    try:
        both = editor.cmd(f"CheckGameCompatibility -Scene {PITCH}")
        assert "'Game'\tcompatible" in both and "'Empty game'\tincompatible" in both, "without -Game every Game of the project answers"
        verdict = editor.cmd(f"CheckGameCompatibility -Scene {PITCH} -Game {empty}")
        assert "incompatible" in verdict and "needs module SoccerGame" in verdict and "SoccerBall" in verdict, "the message names the module and what needs it"
        assert MODULE_ASSET in verdict and PITCH in verdict, "and says how to find both"
    finally:
        remove_asset("Game", empty)


def test_a_level_is_checked_through_its_scenes(editor, pitch_saved):
    reply = editor.cmd(f"CheckGameCompatibility -Level {SOCCER_LEVEL}")
    assert "Scenes read=1" in reply and "'Game'\tcompatible" in reply
    assert "give -Scene or -Level" in editor.cmd("CheckGameCompatibility")
    assert "not a Game asset" in editor.cmd(f"CheckGameCompatibility -Scene {PITCH} -Game {MODULE_ASSET}")


def test_the_scenes_that_use_a_module_are_found_from_their_files(editor, pitch_saved):
    found = {r[0]: r for r in rows(editor.cmd(f"ListScenesUsingModule -Module {MODULE_ASSET}"))}
    assert PITCH in found and "SoccerBall" in found[PITCH][2]
    assert "5C0A11E7B2D34F03" not in found, "a scene without components of that module is not listed"
    assert "not a Script-Module" in editor.cmd(f"ListScenesUsingModule -Module 0000000000000001{GAME_TYPE}")


# ---- an entity that cannot be loaded is not forgotten by a Save ------------------------------------------------------------------------------------------------------------------------

PHYSICS_LEVEL = "6162BB6775AC3293"                                              # MyTestLevel: its scene A1B2C3D4E5F60719 is the one the test damages
PHYSICS_SCENE = PROJECT / "Descriptors" / "Scene" / "19" / "07" / "A1B2C3D4E5F60719.desc"


def test_saving_a_scene_does_not_forget_the_entities_that_could_not_be_loaded(editor):
    """An entity whose component is not registered (the game module that defines it is not loaded, or its file is damaged) fails to load and is left out of the world. A Save used to rebuild
    the list of the scene's entities from the world, which unlinked it for good, and wrote ComponentDeps.txt without what it needs. Now the scene keeps them."""
    import shutil
    import tempfile
    backup = pathlib.Path(tempfile.mkdtemp(prefix="xlion_scene_backup_")) / "scene"
    shutil.copytree(PHYSICS_SCENE, backup)
    try:
        entity = PHYSICS_SCENE / "entity_db" / "01" / "01" / "00000101.entity"
        text = entity.read_bytes().decode()
        assert "#296EEAAEE0EF730" in text
        entity.write_bytes(text.replace("#296EEAAEE0EF730", "#DEADBEEF00000001", 1).encode())          # a component no module defines
        deps_file = PHYSICS_SCENE / "ComponentDeps.txt"
        deps = deps_file.read_bytes().decode()
        count = int(re.search(r"\[ ComponentDeps : (\d+) \]", deps)[1])
        ghost = '\n  #DEADBEEF00000001  "Ghost"' + ("     #0" if "Module:G" in deps else "") + "\n"                    # in the columns the file has: a Save of another test may have rewritten it with the Module column
        deps = deps.replace(f"[ ComponentDeps : {count} ]", f"[ ComponentDeps : {count + 1} ]").rstrip() + ghost
        deps_file.write_bytes(deps.encode())
        before = (PHYSICS_SCENE / "Descriptor.txt").read_bytes().decode()
        assert "ActiveEntities[G:0]\"    ;u32    #101" in before

        editor.cmd("Close -Save 0")
        assert editor.cmd(f"OpenLevel -Level {PHYSICS_LEVEL} -Save 0").startswith("Opened Level")
        editor.wait_for("GetPlayState", r"Building=false", timeout=240)
        assert "00000101" not in editor.entities("MyTestLevel", "A1B2C3D4E5F60719"), "the entity is not in the world"
        reply = editor.cmd("Save", allow_disk=True)
        assert "rror" not in reply, reply
        editor.cmd("Close -Save 0")

        after = (PHYSICS_SCENE / "Descriptor.txt").read_bytes().decode()
        assert re.search(r'ActiveEntities\[\]"\s*;s64\s+15\b', after) and re.search(r'ActiveEntities\[G:\d+\]"\s*;u32\s+#101\b', after), "the entity that did not load is still the scene's"
        assert (PHYSICS_SCENE / "entity_db" / "01" / "01" / "00000101.entity").is_file(), "and its file is still there"
        assert "Ghost" in deps_file.read_bytes().decode() or "DEADBEEF00000001" in deps_file.read_bytes().decode(), "ComponentDeps.txt still says what the scene needs"
    finally:
        shutil.rmtree(PHYSICS_SCENE, ignore_errors=True)
        shutil.copytree(backup, PHYSICS_SCENE)
        shutil.rmtree(backup.parent, ignore_errors=True)


# ---- removing a module from the Game ---------------------------------------------------------------------------------------------------------------------------------------------------

def test_a_module_that_an_open_scene_uses_cannot_be_removed_from_the_game_and_nothing_is_built(editor):
    """The refusal comes from the open scene's live components, at once. It used to build the game without the module, on the UI thread, to look at what the new DLL still registered."""
    import time
    open_soccer(editor)
    try:
        builds = editor.log_text().count("rebuilding via cmake")
        started = time.time()
        reply = editor.cmd(f"RemoveProjectModuleReference -Module {MODULE_ASSET}", allow_disk=True)
        assert "refused" in reply and "SoccerBall" in reply and "close the level" in reply, reply
        assert time.time() - started < 10, "answered from data, not from a build"
        assert editor.log_text().count("rebuilding via cmake") == builds, "and nothing was built"
        assert MODULE_ASSET in editor.cmd("ListProjectModuleReferences"), "the module is still in the Game"
    finally:
        editor.cmd("Close -Save 0")
