"""Prefab operations: instantiate, revert, hierarchy overrides, and what ApplyOverrides carries into the prefab.

Every test makes its own prefab (MakePrefab on an entity it built), so none depends on what the example project holds and none can skip
for lack of one. The files a prefab writes are new files, which project_guard removes when the run ends.
"""
import re
import secrets
import shutil
import tempfile
import time
from pathlib import Path

import pytest
from harness import quote
from script_project import PROJECT

PREFAB_TYPE = "16F179B86A628F9D"
FOLDER_TYPE = "C4D90C5F0CC43021"


# ---- helpers ------------------------------------------------------------------------------------------------------------

def _id(level) -> str:
    """An entity id nothing uses: InstantiatePrefab creates the entity itself."""
    return f"7E57{next(level._ids):04X}"


def _make_prefab(level, with_child: bool = False) -> str:
    """A new Prefab asset made from a Transform entity (and a child of it); returns the 16 hex digits InstantiatePrefab takes."""
    _, _, transform = level.find_with_component("Transform")
    lib = level.ed.libraries()[0][0]
    asset = "%016X" % (secrets.randbits(63) | 1) + PREFAB_TYPE
    root = level.new_entity()
    level.ok(f"AddComponent -Scene {level.scene} -Id {root} -Component {transform}")
    if with_child:
        child = f"7E57{next(level._ids):04X}"
        level.ok(f"CreateEntity -Scene {level.scene} -Id {child} -Folder 0 -Parent {root}")
        level.ok(f"AddComponent -Scene {level.scene} -Id {child} -Component {transform}")
    level.ok(f"MakePrefab -Scene {level.scene} -Id {root} -Library {lib} -Asset {asset} -Parent {lib}{FOLDER_TYPE}", allow_disk=True)
    return asset[:16]


def _instantiate(level, prefab: str) -> str:
    entity = _id(level)
    level.ok(f"InstantiatePrefab -Scene {level.scene} -Id {entity} -Prefab {prefab} -Folder 0")
    return entity


def _components(level, entity: str) -> set:
    return set(re.findall(r"\[[0-9A-F]{16}\]\s+(\w+)", level.describe(entity)))


def _position_x(level, entity: str) -> float:
    return float(re.search(r"Transform/Position/X = (\S+)", level.describe(entity))[1])


def _set_position_x(level, entity: str, value: str) -> None:
    """The edit the Inspector makes: Transform/Position/X of the entity, from whatever it is now to value."""
    _, _, transform = level.find_with_component("Transform")
    m = re.search(r"Transform/Position/X = (\S+)\s+\(TypeGuid (\w+)\)", level.describe(entity))
    level.ok(f"SetProperty -Scene {level.scene} -Id {entity} -Component {transform} -Path {quote('Transform/Position/X')}"
             f" -TypeGuid {m[2]} -Before {quote(m[1])} -After {quote(value)}")


def _addable_component(level, entity: str, avoid=()):
    """Adds to the entity the first component type it does not have (and that is not in avoid); returns (guid, name)."""
    have = _components(level, entity)
    for line in level.cmd("ListComponentTypes").splitlines():
        m = re.match(r"([0-9A-F]{16})\s+(\S+)\s+(\w+)", line)
        if not m or m[3] in have or m[3] in avoid or "builder" in m[2]:
            continue
        if level.cmd(f"AddComponent -Scene {level.scene} -Id {entity} -Component {m[1]}") == "":
            return m[1], m[3]
    raise AssertionError("no component could be added to the instance")


# ---- instantiate and revert ---------------------------------------------------------------------------------------------

def test_prefab_operations(level):
    """Instantiating a prefab puts an instance in the scene that knows its prefab."""
    prefab = _make_prefab(level)
    entity = _instantiate(level, prefab)
    assert entity in level.entities()
    assert "Transform" in _components(level, entity)
    # it is a prefab instance: the prefab commands take it, and refuse an entity that is not one
    level.ok(f"RevertAllOverrides -Scene {level.scene} -Id {entity}")
    assert "not a prefab instance" in level.cmd(f"RevertAllOverrides -Scene {level.scene} -Id {level.new_entity()}")


def test_revert_override(level):
    """RevertOverride puts one overridden property back to the prefab's value."""
    prefab = _make_prefab(level)
    entity = _instantiate(level, prefab)
    base = _position_x(level, entity)
    _, _, transform = level.find_with_component("Transform")

    _set_position_x(level, entity, "999.000000")
    assert _position_x(level, entity) == 999.0

    m = re.search(r"Transform/Position/X = (\S+)\s+\(TypeGuid (\w+)\)", level.describe(entity))
    level.ok(f"RevertOverride -Scene {level.scene} -Id {entity} -Component {transform} -Path {quote('Transform/Position/X')}"
             f" -TypeGuid {m[2]} -Before {quote(m[1])} -After {quote('%f' % base)}")
    assert _position_x(level, entity) == base


def test_revert_all_overrides(level):
    """RevertAllOverrides rebuilds the instance from the prefab: the edit is gone, the entity is still there."""
    prefab = _make_prefab(level)
    entity = _instantiate(level, prefab)
    base = _position_x(level, entity)
    _set_position_x(level, entity, "999.000000")

    level.ok(f"RevertAllOverrides -Scene {level.scene} -Id {entity}")
    assert entity in level.entities()
    assert _position_x(level, entity) == base


def test_revert_hierarchy_overrides(level):
    """RevertHierarchyOverrides on an instance without hierarchy overrides changes nothing."""
    prefab = _make_prefab(level)
    entity = _instantiate(level, prefab)
    before = level.describe(entity)
    level.ok(f"RevertHierarchyOverrides -Scene {level.scene} -Id {entity}")
    assert level.describe(entity) == before


def test_delete_child_of_instance_and_undo(level):
    """Deleting a child of a prefab instance works, and Undo brings it back."""
    prefab = _make_prefab(level, with_child=True)
    before = set(level.entities())
    entity = _instantiate(level, prefab)
    children = set(level.entities()) - before - {entity}
    assert children, "a prefab made from an entity with a child should instantiate that child"
    child = sorted(children)[0]

    level.ok(f"DeleteEntity -Scene {level.scene} -Id {child}")
    assert child not in level.entities()

    level.cmd("Undo")
    assert child in level.entities()


# ---- ApplyOverrides: what reaches the prefab ----------------------------------------------------------------------------

def test_apply_overrides_carries_added_and_removed_components(level):
    """A component added to a prefab instance becomes the prefab's own on ApplyOverrides, and one removed from it leaves the prefab."""
    prefab = _make_prefab(level)
    root = _instantiate(level, prefab)
    guid, name = _addable_component(level, root)

    level.ok(f"ApplyOverrides -Scene {level.scene} -Id {root}", allow_disk=True)
    assert name in _components(level, _instantiate(level, prefab)), f"{name} should now be part of the prefab"

    level.ok(f"RemoveComponent -Scene {level.scene} -Id {root} -Component {guid}")
    level.ok(f"ApplyOverrides -Scene {level.scene} -Id {root}", allow_disk=True)
    assert name not in _components(level, _instantiate(level, prefab)), f"{name} should have left the prefab"


def test_apply_overrides_with_nothing_changed_keeps_the_prefab(level):
    """Applying an instance that differs from its prefab in nothing must neither add nor strip a component (nor move a value)."""
    prefab = _make_prefab(level)
    first = _instantiate(level, prefab)
    expected_components, expected_x = _components(level, first), _position_x(level, first)

    level.ok(f"ApplyOverrides -Scene {level.scene} -Id {first}", allow_disk=True)
    again = _instantiate(level, prefab)
    assert _components(level, again) == expected_components
    assert _position_x(level, again) == expected_x
    assert _components(level, first) == expected_components, "the applied instance itself must not change either"


def test_apply_overrides_carries_property_overrides(level):
    """A property edited on the instance becomes the prefab's value (the part of ApplyOverrides that was always there)."""
    prefab = _make_prefab(level)
    root = _instantiate(level, prefab)
    _set_position_x(level, root, "7.000000")

    level.ok(f"ApplyOverrides -Scene {level.scene} -Id {root}", allow_disk=True)
    assert _position_x(level, _instantiate(level, prefab)) == 7.0


def test_apply_overrides_carries_components_and_properties_together(level):
    """Both kinds of change in one Apply: the new component and the new value reach the prefab."""
    prefab = _make_prefab(level)
    root = _instantiate(level, prefab)
    _, name = _addable_component(level, root)
    _set_position_x(level, root, "3.000000")

    level.ok(f"ApplyOverrides -Scene {level.scene} -Id {root}", allow_disk=True)
    fresh = _instantiate(level, prefab)
    assert name in _components(level, fresh)
    assert _position_x(level, fresh) == 3.0


def test_apply_overrides_leaves_other_instances_alone(level):
    """Apply changes the prefab going forward; instances already placed keep what they have."""
    prefab = _make_prefab(level)
    applied, bystander = _instantiate(level, prefab), _instantiate(level, prefab)
    _, name = _addable_component(level, applied)
    bystander_before = _components(level, bystander)

    level.ok(f"ApplyOverrides -Scene {level.scene} -Id {applied}", allow_disk=True)
    assert _components(level, bystander) == bystander_before
    assert name not in _components(level, bystander)


def test_apply_overrides_twice_is_stable(level):
    """A second Apply of the same instance finds nothing left to carry, and the prefab stays as the first one made it."""
    prefab = _make_prefab(level)
    root = _instantiate(level, prefab)
    _, name = _addable_component(level, root)

    level.ok(f"ApplyOverrides -Scene {level.scene} -Id {root}", allow_disk=True)
    level.ok(f"ApplyOverrides -Scene {level.scene} -Id {root}", allow_disk=True)
    assert name in _components(level, _instantiate(level, prefab))


def test_apply_overrides_adds_the_component_to_every_later_instance(level):
    """Not just the first instance made after Apply: each one has the new component."""
    prefab = _make_prefab(level)
    root = _instantiate(level, prefab)
    _, name = _addable_component(level, root)
    level.ok(f"ApplyOverrides -Scene {level.scene} -Id {root}", allow_disk=True)
    for _ in range(3):
        assert name in _components(level, _instantiate(level, prefab))


def test_apply_overrides_on_a_missing_target_says_so(level):
    """A bad target is an answer, not a crash."""
    reply = level.cmd(f"ApplyOverrides -Scene {level.scene} -Id 7E57FFFF", allow_disk=True)
    assert reply and "not found" in reply


def test_apply_overrides_on_a_plain_entity_says_so(level):
    """An entity that is not a prefab instance cannot be applied."""
    plain = level.new_entity()
    reply = level.cmd(f"ApplyOverrides -Scene {level.scene} -Id {plain}", allow_disk=True)
    assert reply, "applying an entity that is not a prefab instance must be refused"


# ---- phase 0 of documentation/Editors/prefabs_plan.md: what a prefab does across a save and a reload, pinned before the storage changes -------------------
#
# Today an instance placed in a Level is stored as one entity file per member (ids minted when it was placed), and its overrides address members by child-index path. The tests below pin
# what that does. The ones marked xfail(strict) are what the plan says is wrong today: they assert what must be true once prefabs are recipes (phase 3) and spawn is built (phase 4), and
# strict means the day one starts passing the run fails until the marker is taken off - the phase that fixed it removes it.
# Phase 3 (instances are recipes: one file per instance, members addressed by their ids in the prefab) took the markers off the two it fixed (a child added to the prefab
# reaches a saved Level; removing a prefab child does not move an override); the physics one waits for phase 4.

def _guid_folder(kind: str, guid: str) -> Path:
    v = int(guid, 16)
    return PROJECT / "Descriptors" / kind / f"{v & 0xFF:02X}" / f"{(v >> 8) & 0xFF:02X}" / f"{v:X}.desc"     # the folder name has no leading zeros (Level/F3/F3/166FAE5EB82F3F3.desc)


@pytest.fixture
def level_files_restored(level):
    """A test that saves the Level writes its entities where the next test (whose ids are the same 7E57xxxx) would find them: the Level's and its Scenes' folders are put back as they were when the test ends
    (project_guard only does that when the whole run ends)."""
    yield from restoring_level_files(level)


def restoring_level_files(level):
    """The body of level_files_restored for any Level fixture (the Soccer one, game_level, too)."""
    folders = [_guid_folder("Level", level.guid)] + [_guid_folder("Scene", scene) for scene, _ in level.scenes]
    backup = Path(tempfile.mkdtemp(prefix="xlion_prefabs_"))
    for i, folder in enumerate(folders):
        shutil.copytree(folder, backup / str(i))
    yield
    try:
        if level.ed.alive():
            level.ed.cmd("Close -Save 0")
    finally:                                         # restored even when the editor died in the test (cmd raises EditorCrashed), or the next test opens what this one saved
        for i, folder in enumerate(folders):
            for attempt in range(50):                # a file the pipeline's watcher is reading may refuse for a moment (it once left a member file missing)
                try:
                    if folder.exists():
                        shutil.rmtree(folder)
                    shutil.copytree(backup / str(i), folder)
                    break
                except OSError:
                    if attempt == 49:
                        raise
                    time.sleep(0.2)
        shutil.rmtree(backup, ignore_errors=True)


def _reload(level, save: bool = True) -> None:
    """Saves the Level (or not), closes it and opens it again: what is in the editor afterwards is only what the files hold."""
    ed = level.ed
    if save:
        assert "rror" not in level.cmd("Save", allow_disk=True)
    ed.cmd("Close -Save 0")
    deadline = time.monotonic() + 15
    while ed.cmd("list").strip() and time.monotonic() < deadline:          # the session is gone before another one is opened (the toolbar's settings handler is released with it)
        time.sleep(0.2)
    assert "Opened" in ed.cmd(f"OpenLevel -Level {level.guid} -Save 0")
    ed.wait_for("GetPlayState", r"Building=false", timeout=240)


def _component_guid(level, name: str) -> str:
    return re.search(rf"^([0-9A-F]{{16}})\s+\S+\s+{name}\b", level.cmd("ListComponentTypes"), re.M)[1]


def _position(level, entity: str, axis: str = "X") -> float:
    return float(re.search(rf"Transform/Position/{axis} = (\S+)", level.describe(entity))[1])


def _set_position(level, entity: str, axis: str, value: str) -> None:
    transform = _component_guid(level, "Transform")
    m = re.search(rf"Transform/Position/{axis} = (\S+)\s+\(TypeGuid (\w+)\)", level.describe(entity))
    level.ok(f"SetProperty -Scene {level.scene} -Id {entity} -Component {transform} -Path {quote(f'Transform/Position/{axis}')}"
             f" -TypeGuid {m[2]} -Before {quote(m[1])} -After {quote(value)}")


def _new_asset(level) -> tuple:
    """(asset guid as the commands take it, library guid, parent folder) for a new Prefab asset."""
    lib = level.ed.libraries()[0][0]
    return "%016X" % (secrets.randbits(63) | 1) + PREFAB_TYPE, lib, f"{lib}{FOLDER_TYPE}"


def _make_variant(level, instance: str) -> str:
    """MakePrefabVariant of an instance: a new prefab whose root is that instance (its overrides included). Returns the 16 hex digits InstantiatePrefab takes."""
    asset, lib, parent = _new_asset(level)
    level.ok(f"MakePrefabVariant -Scene {level.scene} -Id {instance} -Library {lib} -Asset {asset} -Parent {parent}", allow_disk=True)
    return asset[:16]


def _make_prefab_tree(level, xs) -> str:
    """A prefab of a root with one child per value in xs, in that order, each child's Transform/Position/X set to its value (that is how the test tells them apart)."""
    _, _, transform = level.find_with_component("Transform")
    root = level.new_entity()
    level.ok(f"AddComponent -Scene {level.scene} -Id {root} -Component {transform}")
    for x in xs:
        child = f"7E57{next(level._ids):04X}"
        level.ok(f"CreateEntity -Scene {level.scene} -Id {child} -Folder 0 -Parent {root}")
        level.ok(f"AddComponent -Scene {level.scene} -Id {child} -Component {transform}")
        _set_position(level, child, "X", "%f" % x)
    asset, lib, parent = _new_asset(level)
    level.ok(f"MakePrefab -Scene {level.scene} -Id {root} -Library {lib} -Asset {asset} -Parent {parent}", allow_disk=True)
    return asset[:16]


def _members(level, before: set, root: str) -> dict:
    """{id: X} of the entities that appeared since `before`, except the root: the members of the instance just placed."""
    return {e: _position(level, e) for e in set(level.entities()) - before - {root}}


def test_a_child_added_to_a_prefab_after_a_level_was_saved_reaches_that_level(level, level_files_restored):
    """A Level saved with an instance of a prefab with one child; the prefab then gets a second child (through another instance, Apply Overrides); reopen the Level: the instance has both."""
    prefab = _make_prefab(level, with_child=True)
    before = set(level.entities())
    placed = _instantiate(level, prefab)
    assert len(_members(level, before, placed)) == 1
    assert "rror" not in level.cmd("Save", allow_disk=True)

    other = _instantiate(level, prefab)
    extra = f"7E57{next(level._ids):04X}"
    level.ok(f"CreateEntity -Scene {level.scene} -Id {extra} -Folder 0 -Parent {other}")
    level.ok(f"AddComponent -Scene {level.scene} -Id {extra} -Component {_component_guid(level, 'Transform')}")
    level.ok(f"ApplyOverrides -Scene {level.scene} -Id {other}", allow_disk=True)

    _reload(level, save=False)                       # the second instance was never saved; the prefab's file was
    listed = level.cmd(f"ListPrefabOverrides -Scene {level.scene} -Id {placed}").split("Members:\n", 1)[1].split("Orphans:", 1)[0]
    assert len(listed.split()) == 2 * 2, f"the saved instance has BOTH children of the prefab as it is now: {listed}"
    # new since `before`: the placed instance, its two members, and the second child of the instance MakePrefab left (saved with the level: it gets the change too)
    assert len(set(level.entities()) - before) == 1 + 2 + 1


def test_a_new_instance_of_a_changed_prefab_has_the_change(level):
    """The part of the same story that works today: an instance placed after the prefab got its second child has both."""
    prefab = _make_prefab(level, with_child=True)
    other = _instantiate(level, prefab)
    extra = f"7E57{next(level._ids):04X}"
    level.ok(f"CreateEntity -Scene {level.scene} -Id {extra} -Folder 0 -Parent {other}")
    level.ok(f"AddComponent -Scene {level.scene} -Id {extra} -Component {_component_guid(level, 'Transform')}")
    level.ok(f"ApplyOverrides -Scene {level.scene} -Id {other}", allow_disk=True)

    before = set(level.entities())
    placed = _instantiate(level, prefab)
    assert len(_members(level, before, placed)) == 2


def test_instance_members_keep_their_ids_across_save_and_reload(level, level_files_restored):
    """The entities of a placed instance are saved with the ids they were given, and are there with the same ids when the Level is opened again (what the plan keeps by deriving them, phase 3)."""
    prefab = _make_prefab(level, with_child=True)
    placed = _instantiate(level, prefab)
    before = set(level.entities())
    _reload(level)
    assert set(level.entities()) == before
    assert placed in level.entities()


def test_a_reference_to_an_instance_member_survives_save_and_reload(level, level_files_restored):
    """A goal-like entity of the level that points at a member of an instance, and one that points at the instance root: after a save and a reload each still points at the same entity."""
    prefab = _make_prefab(level, with_child=True)
    before = set(level.entities())
    placed = _instantiate(level, prefab)
    (member,) = _members(level, before, placed)

    reference = _component_guid(level, "EntityReference")

    def refer(holder: str, target: str) -> None:
        level.ok(f"AddComponent -Scene {level.scene} -Id {holder} -Component {reference}")
        level.ok(f"SetEntityReference -Scene {level.scene} -Id {holder} -Component {reference} -Path EntityReference/Target -AfterScene {level.scene} -AfterId {target}")

    def target_of(holder: str) -> str:
        return re.search(r"EntityReference/Target = (.+?)\s+\(TypeGuid", level.describe(holder))[1]

    to_member, to_root = level.new_entity(), level.new_entity()
    refer(to_member, member)
    refer(to_root, placed)
    _reload(level)

    probe_member, probe_root = level.new_entity(), level.new_entity()     # what a reference to each is now, asked of the editor after the reload
    refer(probe_member, member)
    refer(probe_root, placed)
    assert target_of(to_member) != "invalid" and target_of(to_member) == target_of(probe_member)
    assert target_of(to_root) != "invalid" and target_of(to_root) == target_of(probe_root)
    assert target_of(to_member) != target_of(to_root)


def test_a_variant_override_of_the_base_survives_save_and_reload(level, level_files_restored):
    """A variant (a prefab whose root is an instance of another) keeps what was overridden in it, and an instance of the variant can override the base's property again; both survive a reload."""
    base = _make_prefab(level)
    source = _instantiate(level, base)
    _set_position(level, source, "X", "5.000000")
    variant = _make_variant(level, source)

    plain, edited = _instantiate(level, variant), _instantiate(level, variant)
    assert _position(level, plain) == 5.0, "an instance of the variant starts from the variant's override of the base"
    _set_position(level, edited, "X", "11.000000")
    _reload(level)
    assert _position(level, plain) == 5.0
    assert _position(level, edited) == 11.0


def test_a_variant_of_a_variant_keeps_the_overrides_of_every_level_across_save_and_reload(level, level_files_restored):
    """Nested two deep (the only nesting the commands can make: no command moves an entity under another, so a member that is itself an instance cannot be built; a variant is an instance as the root
    of a prefab): base <- variant 1 (X=5) <- variant 2 (Y=7) <- an instance with its own override (Z=9). Every level's value reaches it, before and after a save and a reload."""
    base = _make_prefab(level)
    one = _instantiate(level, base)
    _set_position(level, one, "X", "5.000000")
    variant1 = _make_variant(level, one)

    two = _instantiate(level, variant1)
    _set_position(level, two, "Y", "7.000000")
    variant2 = _make_variant(level, two)

    leaf = _instantiate(level, variant2)
    _set_position(level, leaf, "Z", "9.000000")
    expected = (5.0, 7.0, 9.0)
    assert tuple(_position(level, leaf, a) for a in "XYZ") == expected

    _reload(level)
    assert tuple(_position(level, leaf, a) for a in "XYZ") == expected
    fresh = _instantiate(level, variant2)
    assert tuple(_position(level, fresh, a) for a in "XYZ") == (5.0, 7.0, 0.0), "a new instance of the last variant has the two inner levels' values and none of the instance's own"


def test_removing_a_child_of_a_prefab_does_not_move_an_override_to_another_member(level):
    """A prefab of three children (X = 10, 20, 30). An instance overrides the middle one (X=99). The prefab loses its first child (through another instance, Apply Overrides), then the override is
    applied to the prefab: it must land on the middle child, which is now the first. By index path it lands on whatever is second now."""
    prefab = _make_prefab_tree(level, [10, 20, 30])
    before = set(level.entities())
    mine = _instantiate(level, prefab)
    middle = next(e for e, x in _members(level, before, mine).items() if x == 20.0)
    _set_position(level, middle, "X", "99.000000")

    before = set(level.entities())
    other = _instantiate(level, prefab)
    first = next(e for e, x in _members(level, before, other).items() if x == 10.0)
    level.ok(f"DeleteEntity -Scene {level.scene} -Id {first}")
    level.ok(f"ApplyOverrides -Scene {level.scene} -Id {other}", allow_disk=True)

    level.ok(f"ApplyOverrides -Scene {level.scene} -Id {mine}", allow_disk=True)
    before = set(level.entities())
    fresh = _instantiate(level, prefab)
    assert sorted(_members(level, before, fresh).values()) == [30.0, 99.0], "the prefab is the middle child with 99 and the last one with 30"


def test_a_prefab_with_a_collider_spawned_during_play_gets_a_physics_body(level, level_files_restored):
    """The editor places an instance with the same call a game spawns with (prefab::mgr::Spawn, phase 4: staged and built when the world runs builders). One placed before Play is built when Play loads
    the Level (it has a body); one placed while Playing has one too. A body is there when Physics/BodyGeneration is not 0."""
    ed = level.ed
    root = level.new_entity()
    for part in ("Transform", "Physics", "PhysicsBodyProperties", "PhysicsColliderBox", "PhysicsDynamics"):
        level.ok(f"AddComponent -Scene {level.scene} -Id {root} -Component {_component_guid(level, part)}")
    asset, lib, parent = _new_asset(level)
    level.ok(f"MakePrefab -Scene {level.scene} -Id {root} -Library {lib} -Asset {asset} -Parent {parent}", allow_disk=True)
    prefab = asset[:16]
    placed = _instantiate(level, prefab)
    assert "rror" not in level.cmd("Save", allow_disk=True)

    assert ed.cmd("Play", allow_disk=True).startswith("Play requested")
    ed.wait_play_state("Playing", timeout=120)
    generation = lambda e: float(re.search(r"Physics/BodyGeneration = (\S+)", level.describe(e))[1])
    assert generation(placed) != 0, "the instance placed before Play is built with the rest of the Level"

    spawned = _instantiate(level, prefab)
    assert generation(spawned) != 0, "the instance spawned while Playing has a body"
    assert "PhysicsColliderBox" not in _components(level, spawned), "builder components are consumed when an entity is created"


# ---- phase 1 of documentation/Editors/prefabs_plan.md: a prefab is stored as a scene ------------------------------------------------------------------------------------------------------------
#
# golden/prefab_v1 holds the example project's prefabs as they were before phase 1 (one Entity.txt with every member, "LocalId" records): the format the old reader still reads and converts.

PREFAB_V1 = Path(__file__).parent / "golden" / "prefab_v1"


def _old_prefab_copy(src: Path) -> tuple:
    """A copy of an old-format prefab under a new guid (the files only: no info.txt, so it is no asset of the library; InstantiatePrefab does not need one). Returns (guid, folder)."""
    guid = "%016X" % (secrets.randbits(63) | 1)
    folder = _guid_folder("Prefab", guid)
    folder.mkdir(parents=True)
    for f in src.iterdir():
        shutil.copy2(f, folder / f.name)
    return guid, folder


def test_every_example_prefab_reads_the_same_from_the_old_format(game_level):
    """Each prefab of the example project as it was written before phase 1, read by the old reader (converted on load), gives an instance with the same components and values as the
    example project's prefab as it is now. 7E5700000000B001 has a Parent record written before Follow was a field (it loads since phase 1: the reader gives it the default Follow).
    66879B27D9D067FB uses a component no module registers any more: it does not load, in either format (it is the user's data, left as it is)."""
    lv = game_level
    loaded = 0
    for src in sorted(p for p in PREFAB_V1.iterdir() if p.is_dir()):
        copy, folder = _old_prefab_copy(src)
        try:
            def place(prefab: str) -> tuple:
                """(reply, the describes of the instance's entities: the root's first, then its members', sorted; runtime handles - which entity a reference names this time - left out)."""
                before, root = set(lv.entities()), _id(lv)
                reply = lv.cmd(f"InstantiatePrefab -Scene {lv.scene} -Id {root} -Prefab {prefab} -Folder 0")
                if reply:
                    return reply, []
                text = lambda e: re.sub(r"runtime-entity [0-9A-F]+", "runtime-entity", lv.describe(e))
                return reply, [text(root)] + sorted(text(e) for e in set(lv.entities()) - before - {root})

            r_old, d_old = place(copy)
            r_new, d_new = place(src.name)
            assert (r_old == "") == (r_new == ""), f"{src.name}: the old file says {r_old!r}, the project's prefab says {r_new!r}"
            if r_old:
                continue
            loaded += 1
            assert d_old == d_new, f"{src.name}: the instance of the old file differs from the instance of the project's prefab"
        finally:
            shutil.rmtree(folder, ignore_errors=True)
    assert loaded >= 9, f"only {loaded} of the example prefabs loaded"


def test_a_prefab_is_stored_as_a_scene(level):
    """MakePrefab of a root with a child writes the scene format: a descriptor naming the root and both members, one entity file per member, ComponentDeps.txt, and no Entity.txt."""
    prefab = _make_prefab(level, with_child=True)
    folder = _guid_folder("Prefab", prefab)
    descriptor = (folder / "Descriptor.txt").read_bytes().decode()
    assert re.search(r'"Prefab/Root"\s+;u64\s+#[0-9A-F]+', descriptor), descriptor          # 64 bits since the ids were widened (prefab plan phase 2)
    assert re.search(r'"Prefab/ActiveEntities\[\]"\s+;s64\s+2\b', descriptor), descriptor
    assert len(list((folder / "entity_db").rglob("*.entity"))) == 2
    assert (folder / "ComponentDeps.txt").is_file() and "Transform" in (folder / "ComponentDeps.txt").read_bytes().decode()
    assert not (folder / "Entity.txt").exists()


def test_a_prefab_keeps_the_names_of_its_entities(level):
    """The names the entities had in the scene become the prefab's (its descriptor's EntityNames), and an Apply Overrides (which saves the prefab again) keeps them."""
    _, _, transform = level.find_with_component("Transform")
    root, child = level.new_entity(), f"7E57{next(level._ids):04X}"
    level.ok(f"AddComponent -Scene {level.scene} -Id {root} -Component {transform}")
    level.ok(f"CreateEntity -Scene {level.scene} -Id {child} -Folder 0 -Parent {root}")
    level.ok(f"RenameEntity -Scene {level.scene} -Id {root} -Name {quote('Crate Root')}")
    level.ok(f"RenameEntity -Scene {level.scene} -Id {child} -Name {quote('Crate Lid')}")
    asset, lib, parent = _new_asset(level)
    level.ok(f"MakePrefab -Scene {level.scene} -Id {root} -Library {lib} -Asset {asset} -Parent {parent}", allow_disk=True)
    descriptor = _guid_folder("Prefab", asset[:16]) / "Descriptor.txt"

    def names() -> set:
        return set(re.findall(r'"Prefab/EntityNames\[G:\d+\]/Name"\s+;string\s+"([^"]*)"', descriptor.read_bytes().decode()))

    assert names() == {"Crate Root", "Crate Lid"}
    instance = _instantiate(level, asset[:16])
    _set_position_x(level, instance, "2.000000")
    level.ok(f"ApplyOverrides -Scene {level.scene} -Id {instance}", allow_disk=True)
    assert names() == {"Crate Root", "Crate Lid"}


def test_make_prefab_of_a_group_whose_members_reference_each_other(level, level_files_restored):
    """Phase 0, finding 2: MakePrefab of a root whose child references it (and which references the child) used to end the Debug editor (Save found the references of the copy still pointing
    at the entities it was copied from). Now the prefab's references point at its own members: in the instance MakePrefab leaves, in a new instance, and in an instance made after a reload
    (the prefab read from its files)."""
    _, _, transform = level.find_with_component("Transform")
    reference = _component_guid(level, "EntityReference")
    root, child = level.new_entity(), f"7E57{next(level._ids):04X}"
    level.ok(f"AddComponent -Scene {level.scene} -Id {root} -Component {transform}")
    level.ok(f"CreateEntity -Scene {level.scene} -Id {child} -Folder 0 -Parent {root}")

    def refer(holder: str, target: str) -> None:
        level.ok(f"SetEntityReference -Scene {level.scene} -Id {holder} -Component {reference} -Path EntityReference/Target -AfterScene {level.scene} -AfterId {target}")

    def target_of(holder: str) -> str:
        return re.search(r"EntityReference/Target = (.+?)\s+\(TypeGuid", level.describe(holder))[1]

    for holder in (root, child):
        level.ok(f"AddComponent -Scene {level.scene} -Id {holder} -Component {reference}")
    refer(child, root)
    refer(root, child)
    before = set(level.entities()) - {root, child}
    asset, lib, parent = _new_asset(level)
    level.ok(f"MakePrefab -Scene {level.scene} -Id {root} -Library {lib} -Asset {asset} -Parent {parent}", allow_disk=True)
    prefab = asset[:16]

    def check(instance_root: str, before: set) -> None:
        (member,) = set(level.entities()) - before - {instance_root}
        probe = level.new_entity()                                        # what a reference to the instance's root prints
        level.ok(f"AddComponent -Scene {level.scene} -Id {probe} -Component {reference}")
        refer(probe, instance_root)
        assert target_of(member) == target_of(probe) != "invalid", "the member references its own instance's root"
        refer(probe, member)
        assert target_of(instance_root) == target_of(probe) != "invalid", "the root references its own instance's member"

    check(root, before)                                                    # the group MakePrefab turned into an instance
    before = set(level.entities())
    check(_instantiate(level, prefab), before)
    _reload(level)
    before = set(level.entities())
    check(_instantiate(level, prefab), before)


def test_upgrade_project_converts_a_prefab_of_the_old_format(game_level):
    """UpgradeProject saves every prefab still in the old format (one Entity.txt) in the scene format; an instance of it is what the old file gave. One that cannot be read is listed and left as it is."""
    lv = game_level
    src = PREFAB_V1 / "267C4C533488E711"                               # a Soccer keeper: the Game's components
    copy, folder = _old_prefab_copy(src)
    try:
        reply = lv.cmd("UpgradeProject", allow_disk=True)
        assert re.search(rf"^\s+{copy}\s*$", reply, re.M), reply
        assert "66879B27D9D067FB" in reply.split("Left as they are:")[-1], "a prefab that cannot be read is listed, with why, not converted"
        assert "no longer registered" in reply.split("Left as they are:")[-1]
        assert (_guid_folder("Prefab", "66879B27D9D067FB") / "Entity.txt").is_file()
        assert not (folder / "Entity.txt").exists() and len(list((folder / "entity_db").rglob("*.entity"))) == 1
        assert re.search(r'"Prefab/Root"', (folder / "Descriptor.txt").read_bytes().decode())

        converted, original = _id(lv), _id(lv)
        lv.ok(f"InstantiatePrefab -Scene {lv.scene} -Id {converted} -Prefab {copy} -Folder 0")
        lv.ok(f"InstantiatePrefab -Scene {lv.scene} -Id {original} -Prefab {src.name} -Folder 0")
        assert lv.describe(converted) == lv.describe(original)
        assert "0 prefab(s) converted" in lv.cmd("UpgradeProject", allow_disk=True), "nothing left to convert but what cannot be read"
    finally:
        shutil.rmtree(folder, ignore_errors=True)
