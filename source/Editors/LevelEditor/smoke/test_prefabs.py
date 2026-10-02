"""Prefab operations: instantiate, revert, hierarchy overrides, and what ApplyOverrides carries into the prefab.

Every test makes its own prefab (MakePrefab on an entity it built), so none depends on what the example project holds and none can skip
for lack of one. The files a prefab writes are new files, which project_guard removes when the run ends.
"""
import re
import secrets

import pytest
from harness import b64

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
    level.ok(f"SetProperty -Scene {level.scene} -Id {entity} -Component {transform} -Path {b64('Transform/Position/X')}"
             f" -TypeGuid {m[2]} -Before {b64(m[1])} -After {b64(value)}")


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
    level.ok(f"RevertOverride -Scene {level.scene} -Id {entity} -Component {transform} -Path {b64('Transform/Position/X')}"
             f" -TypeGuid {m[2]} -Before {b64(m[1])} -After {b64('%f' % base)}")
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
