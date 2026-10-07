"""Prefab instances are recipes (documentation/Editors/prefabs_plan.md, phase 3), in the editor.

A level stores an instance as one entity file (its recipe); its members are spawned from the prefab when the level loads, with ids derived from
the instance's id and their address (the member's id in its prefab, one per nested instance crossed). What these tests hold:

  * a level saved before recipes (golden/scenes_v1: the example project's scenes as they were) converts when it is opened and reads the same,
    and again once saved and reopened;
  * an override stays on its member when the prefab's children are reordered;
  * a prefab holding an instance as a member (InstantiatePrefab -Parent, then MakePrefab of the parent): an override inside the nested instance,
    saved and reloaded;
  * orphan overrides are listed and can be removed (undoable);
  * MakePrefab keeps a member's reference to an entity outside the group as an override of the instance; Apply maps a reference to an instance
    member to the prefab's member.
"""
import json
import re
import shutil
import tempfile
import time
from pathlib import Path

import pytest
from harness import quote
from test_prefabs import (_component_guid, _guid_folder, _instantiate, _make_prefab, _make_prefab_tree, _new_asset, _position, _reload,
                          _set_position, level_files_restored)      # noqa: F401  (a fixture and the helpers of the prefab tests)

SCENES_V1 = Path(__file__).parent / "golden" / "scenes_v1"


def _members(level, root: str) -> dict:
    """{member id: address} of an instance, from ListPrefabOverrides."""
    text = level.cmd(f"ListPrefabOverrides -Scene {level.scene} -Id {root}")
    section = text.split("Members:\n", 1)[1].split("Orphans:", 1)[0]
    return {m[1]: m[2] for m in re.finditer(r"^\s+(\w+)\s+(\S+)\s*$", section, re.M)}


def _orphans(level, root: str) -> int:
    return int(re.search(r"Orphans: (\d+)", level.cmd(f"ListPrefabOverrides -Scene {level.scene} -Id {root}"))[1])


def _target_of(level, holder: str) -> str:
    return re.search(r"EntityReference/Target = (.+?)\s+\(TypeGuid", level.describe(holder))[1]


def _refer(level, holder: str, target: str) -> None:
    level.ok(f"SetEntityReference -Scene {level.scene} -Id {holder} -Component {_component_guid(level, 'EntityReference')} -Path EntityReference/Target -AfterScene {level.scene} -AfterId {target}")


def _probe(level, target: str) -> str:
    """What a reference to target prints (asked of the editor: the handle is per run)."""
    probe = level.new_entity()
    level.ok(f"AddComponent -Scene {level.scene} -Id {probe} -Component {_component_guid(level, 'EntityReference')}")
    _refer(level, probe, target)
    return _target_of(level, probe)


# ---- a level saved before recipes ---------------------------------------------------------------------------------------------------------------

def _normalized(describe: str) -> str:
    return re.sub(r"runtime-entity [0-9A-F]+", "runtime-entity", describe)


def _replace_folder(folder: Path, source: Path) -> None:
    """folder becomes a copy of source (a file the pipeline's watcher is reading may refuse for a moment: tried again)."""
    for attempt in range(50):
        try:
            if folder.exists():
                shutil.rmtree(folder)
            shutil.copytree(source, folder)
            return
        except OSError:
            if attempt == 49:
                raise
            time.sleep(0.2)


def _is_old_instance(file: Path) -> bool:
    text = file.read_bytes().decode(errors="replace")
    return '"EditorPrafabInstance/Prefab"' in text and '"EditorPrafabInstance/Format"' not in text


def _check_old_level_converts(lv, scene: str) -> None:
    golden = json.loads((SCENES_V1 / "describes.json").read_text())[scene]["entities"]
    folder = _guid_folder("Scene", scene)
    lv.ed.cmd("Close -Save 0")                               # nothing holds the scene's files while they are swapped
    deadline = time.monotonic() + 15
    while lv.ed.cmd("list").strip() and time.monotonic() < deadline:
        time.sleep(0.2)
    _replace_folder(folder, SCENES_V1 / scene)               # the scene as the example project had it before recipes

    def check(when: str) -> None:
        ids = set(lv.entities(scene))
        now = {e: _normalized(lv.describe(e, scene)) for e in ids}
        want = [_normalized(d) for d in golden.values()]
        missing = [d for d in want if d not in now.values()]
        extra = {e: d for e, d in now.items() if d not in want}
        assert not missing and not extra and sorted(now.values()) == sorted(want), \
            f"{when}: the entities do not read the same as before recipes\n--- expected, not found:\n" + "\n".join(missing[:2]) + "\n--- found instead:\n" + "\n".join(f"{e}:\n{d}" for e, d in list(extra.items())[:2])
        assert all(len(e) == 16 for e in ids - set(golden)), f"{when}: an id that is not the golden's is a derived one (16 digits)"
        assert len(ids) == len(golden)

    _reload(lv, save=False)                                  # converted when it loads
    check("converted on load")
    _reload(lv, save=True)                                   # written as recipes
    check("saved and reopened")
    listed = [f for f in (folder / "entity_db").rglob("*.entity")]
    assert not any(_is_old_instance(f) for f in listed), "every instance of the scene is a recipe once saved"


def test_an_old_level_converts_when_opened_and_reads_the_same(level, level_files_restored):
    """The Physics scene of the example project as it was saved before recipes (an instance of a two-entity prefab: its member was an entity file of
    the scene): opened, every entity describes as it did with the old code (golden/scenes_v1/describes.json, captured before phase 3), the member with
    a derived id; saved and reopened, the same, and no instance file of the old format is left."""
    scene = "A1B2C3D4E5F60719"
    assert level.scene == scene
    _check_old_level_converts(level, scene)
    assert not (_guid_folder("Scene", scene) / "entity_db" / "DC" / "18" / "C2C318DC.entity").exists(), "the old member's file goes when the converted scene is saved"


def test_the_soccer_level_converts_and_reads_the_same(game_level):
    """The Soccer level (27 instances, overrides on entities added under them by child-index paths): converted on load and once saved, it reads as before."""
    lv = game_level
    scene = "5B388EFC2203EC6F"
    assert lv.scene == scene
    folders = [_guid_folder("Level", lv.guid), _guid_folder("Scene", scene)]
    backup = Path(tempfile.mkdtemp(prefix="xlion_recipes_"))
    for i, f in enumerate(folders):
        shutil.copytree(f, backup / str(i))
    try:
        _check_old_level_converts(lv, scene)
    finally:
        if lv.ed.alive():
            lv.ed.cmd("Close -Save 0")
        for i, f in enumerate(folders):
            _replace_folder(f, backup / str(i))
        shutil.rmtree(backup, ignore_errors=True)


# ---- addresses ----------------------------------------------------------------------------------------------------------------------------------

def test_reordering_a_prefabs_children_keeps_every_override_on_its_member(level, level_files_restored):
    """A prefab of three children (X = 10, 20, 30); an instance overrides the middle one (X=99) and is saved. The prefab's file is edited so its
    root lists the children the other way round; the Level reopened: the members keep their ids, and 99 is still on the member that had 20."""
    prefab = _make_prefab_tree(level, [10, 20, 30])
    mine = _instantiate(level, prefab)
    members = _members(level, mine)
    middle = next(e for e in members if _position(level, e) == 20.0)
    _set_position(level, middle, "X", "99.000000")
    assert "rror" not in level.cmd("Save", allow_disk=True)

    folder = _guid_folder("Prefab", prefab)
    root = re.search(r'"Prefab/Root"\s+;u64\s+#([0-9A-F]+)', (folder / "Descriptor.txt").read_bytes().decode())[1]
    v = int(root, 16)
    file = folder / "entity_db" / f"{v & 0xFF:02X}" / f"{(v >> 8) & 0xFF:02X}" / f"{v:08X}.entity"
    text = file.read_bytes().decode()
    m = re.search(r"(\[ AllChildren : 3 \]\r?\n[^\n]*\n[^\n]*\n)((?:[^\n]*\n){3})", text)
    assert m, text
    rows = m[2].splitlines(keepends=True)
    file.write_bytes((text[:m.start(2)] + "".join(reversed(rows)) + text[m.end(2):]).encode())

    _reload(level, save=False)
    assert _members(level, mine) == members, "the members keep their ids"
    assert {e: _position(level, e) for e in members} == {e: (99.0 if e == middle else _position(level, e)) for e in members}
    assert sorted(_position(level, e) for e in members) == [10.0, 30.0, 99.0]
    assert _position(level, middle) == 99.0


def test_a_prefab_holding_an_instance_as_a_member(level, level_files_restored):
    """InstantiatePrefab -Parent puts an instance (of a prefab with a child) under an entity; MakePrefab of that entity makes a prefab whose member
    is a nested instance. An instance of it has the nested instance's members, addressed through it (two ids); an override on the inner child
    survives a save and a reload, with the same ids; a fresh instance has the prefab's value."""
    inner = _make_prefab(level, with_child=True)
    holder = level.new_entity()
    level.ok(f"AddComponent -Scene {level.scene} -Id {holder} -Component {_component_guid(level, 'Transform')}")
    nested = f"7E57{next(level._ids):04X}"
    level.ok(f"InstantiatePrefab -Scene {level.scene} -Id {nested} -Prefab {inner} -Folder 0 -Parent {holder}")
    assert nested in level.entities()
    assert f"Parent/Parent = {_probe(level, holder)}" in level.describe(nested)

    asset, lib, parent = _new_asset(level)
    level.ok(f"MakePrefab -Scene {level.scene} -Id {holder} -Library {lib} -Asset {asset} -Parent {parent}", allow_disk=True)
    outer = asset[:16]

    placed = _instantiate(level, outer)
    members = _members(level, placed)
    deep = [e for e, a in members.items() if a.count("/") == 1]
    assert len(members) == 2 and len(deep) == 1, members              # the nested instance's root, and its child through it
    _set_position(level, deep[0], "X", "42.000000")
    _reload(level)
    assert _members(level, placed) == members
    assert _position(level, deep[0]) == 42.0

    fresh = _instantiate(level, outer)
    fresh_deep = [e for e, a in _members(level, fresh).items() if a.count("/") == 1]
    assert len(fresh_deep) == 1 and _position(level, fresh_deep[0]) != 42.0


def test_instantiate_under_a_parent_and_undo(level):
    """-Parent: the instance is the parent's child; Undo takes it (and its members) away and the parent's children list with it."""
    prefab = _make_prefab(level, with_child=True)
    parent = level.new_entity()
    before = set(level.entities())
    root = _instantiate_under(level, prefab, parent)
    assert f"Parent/Parent = {_probe(level, parent)}" in level.describe(root)
    added = set(level.entities()) - before
    assert root in added and len(added) == 1 + 1 + 1           # the root, its member, the probe
    level.cmd("Undo")                                          # the probe's reference
    level.cmd("Undo")                                          # the probe's component
    level.cmd("Undo")                                          # the probe
    level.cmd("Undo")                                          # the instance
    assert set(level.entities()) == before
    assert "not found" in level.cmd(f"InstantiatePrefab -Scene {level.scene} -Id 7E57FFF0 -Prefab {prefab} -Folder 0 -Parent 7E57FFFF")


def _instantiate_under(level, prefab: str, parent: str) -> str:
    entity = f"7E57{next(level._ids):04X}"
    level.ok(f"InstantiatePrefab -Scene {level.scene} -Id {entity} -Prefab {prefab} -Folder 0 -Parent {parent}")
    return entity


def test_orphan_overrides_are_listed_and_removed(level):
    """An instance overrides a member; another instance of the prefab removes that member and applies: the first instance's override is an orphan
    (its member is gone from the prefab). ListPrefabOverrides marks it, RemoveOrphanOverrides takes it away, Undo puts it back."""
    prefab = _make_prefab_tree(level, [10, 20])
    mine = _instantiate(level, prefab)
    second = next(e for e in _members(level, mine) if _position(level, e) == 20.0)
    _set_position(level, second, "X", "99.000000")
    assert _orphans(level, mine) == 0

    other = _instantiate(level, prefab)
    gone = next(e for e in _members(level, other) if _position(level, e) == 20.0)
    level.ok(f"DeleteEntity -Scene {level.scene} -Id {gone}")
    level.ok(f"ApplyOverrides -Scene {level.scene} -Id {other}", allow_disk=True)

    listing = level.cmd(f"ListPrefabOverrides -Scene {level.scene} -Id {mine}")
    assert "ORPHAN" in listing and _orphans(level, mine) == 1, listing
    level.ok(f"RemoveOrphanOverrides -Scene {level.scene} -Id {mine}")
    assert _orphans(level, mine) == 0
    level.cmd("Undo")
    assert _orphans(level, mine) == 1


# ---- references ---------------------------------------------------------------------------------------------------------------------------------

def test_make_prefab_keeps_a_reference_to_an_entity_outside_as_an_override(level, level_files_restored):
    """A group whose member references an entity outside it: the prefab cannot keep that reference (null in a new instance), but the instance the
    group becomes keeps it, as an override - after a save and a reload too (Unity's behavior)."""
    reference = _component_guid(level, "EntityReference")
    outside, root = level.new_entity(), level.new_entity()
    level.ok(f"AddComponent -Scene {level.scene} -Id {root} -Component {_component_guid(level, 'Transform')}")
    level.ok(f"AddComponent -Scene {level.scene} -Id {root} -Component {reference}")
    _refer(level, root, outside)
    asset, lib, parent = _new_asset(level)
    level.ok(f"MakePrefab -Scene {level.scene} -Id {root} -Library {lib} -Asset {asset} -Parent {parent}", allow_disk=True)

    assert _target_of(level, root) == _probe(level, outside), "the instance the group became still references the entity outside"
    assert "EntityReference" in level.cmd(f"ListPrefabOverrides -Scene {level.scene} -Id {root}")
    assert _target_of(level, _instantiate(level, asset[:16])) == "invalid", "the prefab itself has it null"
    _reload(level)
    assert _target_of(level, root) == _probe(level, outside)


def test_apply_maps_a_reference_to_an_instance_member_to_the_prefab_member(level):
    """An instance's root references the instance's own member (an override); Apply carries it into the prefab as a reference to the prefab's member:
    a new instance's root references ITS member."""
    reference = _component_guid(level, "EntityReference")
    root = level.new_entity()
    level.ok(f"AddComponent -Scene {level.scene} -Id {root} -Component {_component_guid(level, 'Transform')}")
    level.ok(f"AddComponent -Scene {level.scene} -Id {root} -Component {reference}")
    child = f"7E57{next(level._ids):04X}"
    level.ok(f"CreateEntity -Scene {level.scene} -Id {child} -Folder 0 -Parent {root}")
    asset, lib, parent = _new_asset(level)
    level.ok(f"MakePrefab -Scene {level.scene} -Id {root} -Library {lib} -Asset {asset} -Parent {parent}", allow_disk=True)
    prefab = asset[:16]

    placed = _instantiate(level, prefab)
    (member,) = _members(level, placed)
    _refer(level, placed, member)
    level.ok(f"ApplyOverrides -Scene {level.scene} -Id {placed}", allow_disk=True)

    fresh = _instantiate(level, prefab)
    (fresh_member,) = _members(level, fresh)
    assert _target_of(level, fresh) == _probe(level, fresh_member) != "invalid"
