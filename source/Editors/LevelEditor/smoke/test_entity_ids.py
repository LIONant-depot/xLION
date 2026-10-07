"""64-bit permanent ids (documentation/Editors/prefabs_plan.md, phase 2).

An entity's id is 64 bits now (the ids the editor mints are still 32-bit values; a derived id, phase 3, will use the whole 63 bits below the top one). What these tests hold:

  * the engine (no editor): the text form, the files, the references, the old data - compiled from dependencies/xECSV2/smoke_test_scene_ids.cpp in Debug;
  * the editor: a 64-bit id is an id in every command, listing, undo step and file; an id that fits in 32 bits prints as it always did (8 digits), a larger one with 16;
    the top bit is reserved (an entity reference is an int64 whose negative values are external); a scene written with u32 id rows (before the widening) loads.
"""
import re
import subprocess

import pytest
from harness import quote
from prefab_bench import REPO, build
from script_project import PROJECT
from test_prefabs import _components, _guid_folder, _instantiate, _make_prefab, _reload, level_files_restored      # noqa: F401  (a fixture and the helpers of the prefab tests)

BIG = "7123456789ABCDEF"                  # does not fit in 32 bits
BIG2 = "7123456789ABCDF0"
JUST_PAST_32 = "0000000100000000"
EDGE_32 = "FFFFFFFF"


# ---- the engine ---------------------------------------------------------------------------------------------------------------------------------

@pytest.mark.no_editor
def test_ids_in_the_engine_text_files_references_and_old_data():
    """Compiles smoke_test_scene_ids.cpp in Debug (asserts on) and runs it: see the list at the top of that file."""
    exe = build(debug=True, src=REPO / "dependencies" / "xECSV2" / "smoke_test_scene_ids.cpp")
    r = subprocess.run([str(exe)], capture_output=True, text=True, cwd=exe.parent, timeout=300)
    report = "\n".join(l for l in r.stdout.splitlines() if l.startswith(("STEP", "FAIL", "ALL")) or "CHECK" in l)
    assert r.returncode == 0 and "ALL CHECKS PASSED" in r.stdout, f"{report}\n--- stderr (asserts) ---\n{r.stderr[-3000:]}"
    assert "Assertion" not in r.stderr and "assert" not in r.stderr.lower(), r.stderr[-3000:]


# ---- the editor: commands ----------------------------------------------------------------------------------------------------------------------

def _create(level, entity: str, parent: str | None = None) -> None:
    level.ok(f"CreateEntity -Scene {level.scene} -Id {entity} -Folder 0" + (f" -Parent {parent}" if parent else ""))


def _normalized(level, entity: str) -> str:
    """DescribeEntity without the runtime handles (they change when an entity is made again)."""
    return re.sub(r"runtime-entity [0-9A-F]+", "runtime-entity", level.describe(entity))


def test_an_entity_with_a_64_bit_id_is_listed_and_described_with_that_id(level):
    """The id is printed with 16 hex digits, takes the same in a command (any case), and a 32-bit one still prints with 8."""
    _create(level, BIG)
    entities = level.entities()
    assert BIG in entities and entities[BIG] == f"Entity #{BIG}"
    assert level.describe(BIG) and "not found" not in level.describe(BIG)
    assert level.describe(BIG.lower()) == level.describe(BIG)
    assert level.describe(BIG2) != level.describe(BIG), "another 64-bit id, one nothing has, is another answer (the low 32 bits are not the id)"

    small = level.new_entity()
    assert len(small) == 8 and small in level.entities()

    _create(level, EDGE_32)                                     # the largest id that fits in 32 bits: still 8 digits
    _create(level, JUST_PAST_32)                                # the smallest that does not: 16
    assert EDGE_32 in level.entities() and JUST_PAST_32 in level.entities()


def test_a_short_id_is_the_same_id(level):
    """An id typed with fewer digits (or in lower case) is the number it spells: it prints with 8."""
    level.ok(f"CreateEntity -Scene {level.scene} -Id 7e5712 -Folder 0")
    assert "007E5712" in level.entities()
    assert level.describe("7E5712") == level.describe("007e5712")


def test_the_top_bit_of_an_id_is_reserved(level):
    """An entity reference is an int64 whose negative values are the external table's: an id with the top bit set could never be referenced, so it is refused (by CreateEntity and InstantiatePrefab)."""
    prefab = _make_prefab(level)
    before = set(level.entities())
    for bad in ("8000000000000000", "FFFFFFFFFFFFFFFF"):
        reply = level.cmd(f"CreateEntity -Scene {level.scene} -Id {bad} -Folder 0")
        assert "63 bits" in reply, reply
    assert "63 bits" in level.cmd(f"InstantiatePrefab -Scene {level.scene} -Id FFFFFFFFFFFFFFFF -Prefab {prefab} -Folder 0")
    assert set(level.entities()) == before
    _create(level, "7FFFFFFFFFFFFFFF")                          # the largest id there is
    assert "7FFFFFFFFFFFFFFF" in level.entities()


def test_create_and_delete_of_a_64_bit_id_undo_and_redo(level):
    """The undo step of a command keeps the id whole: undo of a create removes it, redo makes it again, undo of a delete brings back the entity (and its child) under the same ids."""
    _create(level, BIG)
    assert level.cmd("Undo") == "Undone" and BIG not in level.entities()
    assert level.cmd("Redo") and BIG in level.entities()

    _create(level, BIG2, parent=BIG)
    transform = _component(level, "Transform")
    level.ok(f"AddComponent -Scene {level.scene} -Id {BIG} -Component {transform}")
    level.ok(f"AddComponent -Scene {level.scene} -Id {BIG2} -Component {transform}")
    before = {e: _normalized(level, e) for e in (BIG, BIG2)}

    level.ok(f"DeleteEntity -Scene {level.scene} -Id {BIG}")
    assert BIG not in level.entities() and BIG2 not in level.entities(), "the child goes with its parent"
    assert level.cmd("Undo") == "Undone"
    assert BIG in level.entities() and BIG2 in level.entities()
    assert {e: _normalized(level, e) for e in (BIG, BIG2)} == before, "the entities are back as they were, hierarchy included"
    assert level.cmd("Redo") and BIG not in level.entities()
    assert level.cmd("Undo") == "Undone" and BIG in level.entities()


def _folders(level) -> set:
    """The lines of ListFolders (the order a scene lists its folders in is not part of what is saved)."""
    return set(level.cmd(f"ListFolders -Scene {level.scene}").splitlines())


def _component(level, name: str) -> str:
    return re.search(rf"^([0-9A-F]{{16}})\s+\S+\s+{name}\b", level.cmd("ListComponentTypes"), re.M)[1]


def test_property_edit_name_and_component_of_a_64_bit_id_undo(level):
    """SetProperty, RenameEntity and AddComponent write the id into their undo steps: each undo finds the entity again."""
    _create(level, BIG)
    transform = _component(level, "Transform")
    level.ok(f"AddComponent -Scene {level.scene} -Id {BIG} -Component {transform}")
    m = re.search(r"Transform/Position/X = (\S+)\s+\(TypeGuid (\w+)\)", level.describe(BIG))
    before = m[1]
    level.ok(f"SetProperty -Scene {level.scene} -Id {BIG} -Component {transform} -Path {quote('Transform/Position/X')} -TypeGuid {m[2]} -Before {quote(before)} -After {quote('42.000000')}")
    assert re.search(r"Transform/Position/X = 42", level.describe(BIG))
    assert level.cmd("Undo") == "Undone"
    assert re.search(rf"Transform/Position/X = {re.escape(before)}", level.describe(BIG))

    level.ok(f"RenameEntity -Scene {level.scene} -Id {BIG} -Name {quote('Large')}")
    assert level.entities()[BIG] == "Large"
    assert level.cmd("Undo") == "Undone"
    assert level.entities()[BIG] == f"Entity #{BIG}"

    assert level.cmd("Undo") == "Undone"                         # the AddComponent
    assert "Transform" not in _components(level, BIG)
    assert level.cmd("Redo") and "Transform" in _components(level, BIG)


def test_an_entity_reference_to_a_64_bit_id_and_the_move_of_it_into_a_folder(level):
    """A reference to (and from) an entity with a 64-bit id is stored and restored by undo; the folder lists the id with 16 digits, and undo of the folder's removal puts the members back."""
    holder = level.new_entity()
    _create(level, BIG)
    reference = _component(level, "EntityReference")
    level.ok(f"AddComponent -Scene {level.scene} -Id {holder} -Component {reference}")
    level.ok(f"SetEntityReference -Scene {level.scene} -Id {holder} -Component {reference} -Path EntityReference/Target -AfterScene {level.scene} -AfterId {BIG}")
    target = re.search(r"EntityReference/Target = (.+?)\s+\(TypeGuid", level.describe(holder))[1]
    assert target != "invalid"
    level.ok(f"SetEntityReference -Scene {level.scene} -Id {holder} -Component {reference} -Path EntityReference/Target -AfterScene {level.scene} -AfterId 0")
    assert re.search(r"EntityReference/Target = invalid", level.describe(holder))
    assert level.cmd("Undo") == "Undone"
    assert re.search(r"EntityReference/Target = (.+?)\s+\(TypeGuid", level.describe(holder))[1] == target, "undo restored the target by its 64-bit id"

    folder = "F0000001"
    level.ok(f"CreateFolder -Scene {level.scene} -Id {folder} -Parent 0 -Name {quote('Large ids')}")
    level.ok(f"MoveToFolder -Scene {level.scene} -Id {BIG} -Folder {folder}")
    assert f"  - {BIG}" in level.cmd(f"ListFolders -Scene {level.scene}")
    level.ok(f"DeleteFolder -Scene {level.scene} -Id {folder}")
    assert f"  - {BIG}" not in level.cmd(f"ListFolders -Scene {level.scene}") and BIG in level.entities()
    assert level.cmd("Undo") == "Undone"
    assert f"  - {BIG}" in level.cmd(f"ListFolders -Scene {level.scene}"), "the folder is back with its member"
    assert level.cmd("Undo") == "Undone"                         # the move
    assert f"  - {BIG}" not in level.cmd(f"ListFolders -Scene {level.scene}")


def test_an_instance_of_a_prefab_can_have_a_64_bit_id(level):
    """InstantiatePrefab takes the id the caller gives it, whole."""
    prefab = _make_prefab(level, with_child=True)
    level.ok(f"InstantiatePrefab -Scene {level.scene} -Id {BIG} -Prefab {prefab} -Folder 0")
    assert BIG in level.entities() and "Transform" in _components(level, BIG)
    assert level.cmd("Undo") == "Undone" and BIG not in level.entities()
    assert level.cmd("Redo") and BIG in level.entities()
    _instantiate(level, prefab)


# ---- the editor: files --------------------------------------------------------------------------------------------------------------------------

def _scene_files(level):
    return _guid_folder("Scene", level.scene)


def test_entities_with_64_bit_ids_survive_save_and_reload(level, level_files_restored):
    """Save the Level with big ids (a parent and its child, a name, a folder, a reference from a small-id holder); close; open it again: everything is where it was, under the same ids. The files: a 16 digit
    name and the EntityId64 record for the big ones; the ones that fit are as they were."""
    transform = _component(level, "Transform")
    _create(level, BIG)
    _create(level, BIG2, parent=BIG)
    level.ok(f"AddComponent -Scene {level.scene} -Id {BIG} -Component {transform}")
    level.ok(f"AddComponent -Scene {level.scene} -Id {BIG2} -Component {transform}")
    level.ok(f"RenameEntity -Scene {level.scene} -Id {BIG} -Name {quote('The Big One')}")
    holder = level.new_entity()
    reference = _component(level, "EntityReference")
    level.ok(f"AddComponent -Scene {level.scene} -Id {holder} -Component {reference}")
    level.ok(f"SetEntityReference -Scene {level.scene} -Id {holder} -Component {reference} -Path EntityReference/Target -AfterScene {level.scene} -AfterId {BIG2}")
    level.ok(f"CreateFolder -Scene {level.scene} -Id F0000001 -Parent 0 -Name {quote('Folder of the big')}")
    level.ok(f"MoveToFolder -Scene {level.scene} -Id {BIG} -Folder F0000001")
    entities = dict(level.entities())
    folders = _folders(level)

    assert "rror" not in level.cmd("Save", allow_disk=True)
    root = _scene_files(level)
    big_file = next(root.rglob(f"{BIG}.entity"))
    text = big_file.read_bytes().decode()
    assert "EntityId64" in text and BIG in text and "PermanentId:g" in text
    assert (big_file.parent.parent.name, big_file.parent.name) == ("EF", "CD"), "sharded by the low two bytes, as the files of 32-bit ids are"
    small_file = next(root.rglob(f"{holder}.entity"))
    assert "EntityId64" not in small_file.read_bytes().decode(), "an id that fits is written as before the widening"
    descriptor = (root / "Descriptor.txt").read_bytes().decode()
    assert re.search(r'"Scene/ActiveEntities\[G:\d+\]"\s+;u64\s+#' + BIG + r'\b', descriptor), "the descriptor lists the id as a u64 row"

    _reload(level)
    assert level.entities() == entities
    assert _folders(level) == folders
    assert level.entities()[BIG] == "The Big One"
    probe = level.new_entity()
    level.ok(f"AddComponent -Scene {level.scene} -Id {probe} -Component {reference}")
    level.ok(f"SetEntityReference -Scene {level.scene} -Id {probe} -Component {reference} -Path EntityReference/Target -AfterScene {level.scene} -AfterId {BIG2}")
    target = lambda e: re.search(r"EntityReference/Target = (.+?)\s+\(TypeGuid", level.describe(e))[1]
    assert target(holder) != "invalid" and target(holder) == target(probe), "the reference to the 64-bit id was resolved by the load"

    assert "Parent" in level.describe(BIG2), "the child is still a child"
    _reload(level)                                                # a second round trip changes nothing
    assert set(entities) <= set(level.entities())


def test_a_scene_saved_with_u32_id_rows_loads(level, level_files_restored):
    """What the descriptors held before the widening (the ids of the active entities, the names, the folders as u32 rows) is read as it was: the same Level, its descriptors written back the old way."""
    entity = level.new_entity()
    level.ok(f"RenameEntity -Scene {level.scene} -Id {entity} -Name {quote('Old Style')}")
    level.ok(f"CreateFolder -Scene {level.scene} -Id F0000001 -Parent 0 -Name {quote('Old folder')}")
    level.ok(f"MoveToFolder -Scene {level.scene} -Id {entity} -Folder F0000001")
    assert "rror" not in level.cmd("Save", allow_disk=True)
    entities = dict(level.entities())
    folders = _folders(level)

    changed = 0
    for scene, _ in level.scenes:
        path = _guid_folder("Scene", scene) / "Descriptor.txt"
        text = path.read_bytes().decode()
        rows = r'("Scene/(?:ActiveEntities\[G:\d+\]|EntityNames\[G:\d+\]/Id|Folders\[G:\d+\]/Entities\[G:\d+\]|ExternalRefs\[G:\d+\]/ParentEntity)"\s+);u64'
        text, n = re.subn(rows, r"\1;u32", text)
        changed += n
        path.write_bytes(text.encode())
    assert changed >= 3, "the scenes list entities, a name and a folder member: their rows were u64 and are u32 now"

    _reload(level, save=False)
    assert level.entities() == entities
    assert _folders(level) == folders
    assert level.entities()[entity] == "Old Style"


# ---- the editor: a scene that depends on another ------------------------------------------------------------------------------------------------

def _other_scene(level) -> str:
    """A Scene asset of the project that is not the Level's (the example project has three), as the 16 hex digits the commands take."""
    for scene_dir in sorted((PROJECT / "Descriptors" / "Scene").glob("*/*/*.desc")):
        guid = f"{int(scene_dir.name.split('.')[0], 16):016X}"
        if guid not in {s for s, _ in level.scenes}:
            return guid
    pytest.skip("the example project has only the Level's Scene")


def test_removing_a_scene_dependency_that_clears_a_reference_to_a_64_bit_id_undoes(level, level_files_restored):
    """A scene that refers to an entity of its parent scene (an id past 32 bits): RemoveSceneDependency -ClearRefs 1 nulls the reference, and Undo puts the reference and the edge back - the undo step holds the holder's and the target's ids whole."""
    parent = _other_scene(level)
    level.ok(f"AddScene -Level {level.guid} -Scene {parent}")             # AddScene only lists it: the Level is saved and opened again to have the scene open
    _reload(level)
    assert parent in level.cmd("ListScenes")
    level.ok(f"AddSceneDependency -Scene {level.scene} -Parent {parent}", allow_disk=True)

    level.ok(f"CreateEntity -Scene {parent} -Id {BIG} -Folder 0")
    holder = level.new_entity()
    reference = _component(level, "EntityReference")
    level.ok(f"AddComponent -Scene {level.scene} -Id {holder} -Component {reference}")
    level.ok(f"SetEntityReference -Scene {level.scene} -Id {holder} -Component {reference} -Path EntityReference/Target -AfterScene {parent} -AfterId {BIG}")
    target = lambda: re.search(r"EntityReference/Target = (.+?)\s+\(TypeGuid", level.describe(holder))[1]
    assert target() != "invalid"
    pointing = target()

    assert "can't remove" in level.cmd(f"RemoveSceneDependency -Scene {level.scene} -Parent {parent}", allow_disk=True).lower(), "without -ClearRefs the command refuses: the reference would break"
    level.ok(f"RemoveSceneDependency -Scene {level.scene} -Parent {parent} -ClearRefs 1", allow_disk=True)
    assert target() == "invalid", "the reference to the parent's entity was cleared"
    assert level.cmd("Undo") == "Undone"
    assert target() == pointing, "undo brought the reference back to the same 64-bit id"
