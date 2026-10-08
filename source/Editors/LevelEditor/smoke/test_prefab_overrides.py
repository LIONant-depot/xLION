"""The "Prefab Overrides" popup of the Entity Properties (the data behind it), and what it asks the commands to do.

The popup lists what a prefab instance does differently from its prefab: components added, removed, properties modified (old -> new), children removed or
added, orphan overrides, with Revert All / Revert Hierarchy / Apply at its foot. It draws the report that the DescribePrefabOverrides command prints, one line
per item, so these tests drive the popup's data through that command (the pixels - the button, the popup's place, the grey-blue header of an added component,
the prefab row, the confirmation - were looked at in the windowed editor, not here). Revert All's confirmation is the interface's: the command stays directly
runnable, and undoable.
"""
import re

import pytest
from harness import quote
from test_prefabs import (_addable_component, _component_guid, _components, _instantiate, _make_prefab, _make_prefab_tree, _new_asset, _position,
                          _set_position, level_files_restored)      # noqa: F401  (a fixture and the helpers of the prefab tests)
from test_prefab_recipes import _members, _orphans


def _describe(level, entity: str) -> str:
    return level.cmd(f"DescribePrefabOverrides -Scene {level.scene} -Id {entity}")


def _changes(text: str) -> dict:
    m = re.search(r"Changes: (\d+)  ComponentsAdded=(\d+) ComponentsRemoved=(\d+) PropertiesModified=(\d+) Hierarchy=(\d+) Orphans=(\d+)", text)
    assert m, text
    return dict(zip(("total", "added", "removed", "modified", "hierarchy", "orphans"), map(int, m.groups())))


def _child(level, root: str) -> str:
    """The one member of an instance of a prefab with one child."""
    members = _members(level, root)
    assert len(members) == 1, members
    return next(iter(members))


def test_an_instance_with_no_overrides_says_so(level):
    prefab = _make_prefab(level, with_child=True)
    root = _instantiate(level, prefab)
    text = _describe(level, root)
    assert _changes(text) == dict(total=0, added=0, removed=0, modified=0, hierarchy=0, orphans=0), text
    assert re.search(rf"^Instance {root} ", text, re.M) and f"Prefab {prefab}" in text and not re.search(r"^(Member|Hierarchy|Orphan) ", text, re.M), text
    assert "not a prefab instance" in _describe(level, level.new_entity())
    assert "target not found" in _describe(level, "7E57FFFE")


def test_modified_added_and_removed_components_and_hierarchy_are_one_line_each(level):
    """The root's position changed (Modified Transform, old -> new), a component added to the root (Added), the child lost its Transform (Removed), a child
    added under the root and the prefab's own child deleted (Hierarchy rows); the counts are the sum, and a member answers for its instance."""
    prefab = _make_prefab(level, with_child=True)
    root = _instantiate(level, prefab)
    child = _child(level, root)
    old_x = _position(level, root)

    _set_position(level, root, "X", "42.000000")
    extra_guid, extra_name = _addable_component(level, root, avoid=("EditorPrafabInstance",))
    transform = _component_guid(level, "Transform")
    level.ok(f"RemoveComponent -Scene {level.scene} -Id {child} -Component {transform}")
    added = f"7E57{next(level._ids):04X}"
    level.ok(f"CreateEntity -Scene {level.scene} -Id {added} -Folder 0 -Parent {root}")

    text = _describe(level, root)
    c = _changes(text)
    assert c["added"] == 1 and c["removed"] == 1 and c["modified"] == 1 and c["hierarchy"] == 1 and c["orphans"] == 0 and c["total"] == 4, text
    assert re.search(rf'^Member {root} ".*" \(root\)$', text, re.M), text
    assert re.search(rf"^  Added {re.escape(extra_name)}$", text, re.M), text
    assert re.search(r"^  Modified Transform \(1\)$", text, re.M), text
    assert re.search(rf"^    Transform/Position/X: {old_x:.0f}(\.0+)? -> 42(\.0+)?$", text, re.M), text
    assert re.search(r'^Member \w{16} ".*" \S+$', text, re.M) is not None
    assert re.search(r"^  Removed Transform$", text, re.M), text
    assert re.search(rf"^Hierarchy Added {added} ", text, re.M), text
    # a member answers for the instance it belongs to, and the member asked about leads
    assert f"Asked {child}" in _describe(level, child) and _changes(_describe(level, child)) == c
    assert text.index(f"Member {root}") < text.index(f"Member {child}") and _describe(level, child).index(f"Member {child}") < _describe(level, child).index(f"Member {root}")

    # the prefab's own child deleted: a Removed row of the hierarchy
    level.ok(f"DeleteEntity -Scene {level.scene} -Id {child}")
    text = _describe(level, root)
    assert re.search(r'^Hierarchy Removed \w{16} ".*" \S+$', text, re.M), text
    assert _changes(text)["hierarchy"] == 2 and "Member " + child not in text, text


def test_revert_all_clears_the_report_and_undo_brings_it_back(level):
    """The Revert All button asks first (the interface's question), then runs RevertAllOverrides: a plain undoable command that needs no confirmation of its own."""
    prefab = _make_prefab(level, with_child=True)
    root = _instantiate(level, prefab)
    _set_position(level, root, "X", "42.000000")
    extra_guid, _ = _addable_component(level, root, avoid=("EditorPrafabInstance",))
    before = _describe(level, root)
    assert _changes(before)["total"] == 2, before

    level.ok(f"RevertAllOverrides -Scene {level.scene} -Id {root}")
    assert _changes(_describe(level, root))["total"] == 0, _describe(level, root)
    assert _position(level, root) != 42.0

    level.cmd("Undo")
    assert _describe(level, root) == before


def test_the_row_revert_icons_use_the_existing_commands(level):
    """A modified property reverts with RevertOverride, an added component with RemoveComponent (what the icons in front of the rows run)."""
    prefab = _make_prefab(level, with_child=True)
    root = _instantiate(level, prefab)
    old_x = _position(level, root)
    _set_position(level, root, "X", "42.000000")
    extra_guid, extra_name = _addable_component(level, root, avoid=("EditorPrafabInstance",))
    text = _describe(level, root)
    assert _changes(text)["total"] == 2, text

    transform = _component_guid(level, "Transform")
    m = re.search(r"Transform/Position/X = (\S+)\s+\(TypeGuid (\w+)\)", level.describe(root))
    level.ok(f"RevertOverride -Scene {level.scene} -Id {root} -Component {transform} -Path {quote('Transform/Position/X')} -TypeGuid {m[2]} -Before {quote(m[1])} -After {quote('%f' % old_x)}")
    text = _describe(level, root)
    assert "  Modified " not in text and _changes(text)["total"] == 1, text
    level.ok(f"RemoveComponent -Scene {level.scene} -Id {root} -Component {extra_guid}")
    assert _changes(_describe(level, root))["total"] == 0


def test_orphans_are_listed_apart_and_removed(level):
    """An override whose member the prefab no longer has is an Orphan line (counted), no longer in the member's group; RemoveOrphanOverrides takes it away."""
    prefab = _make_prefab_tree(level, [10, 20])
    mine = _instantiate(level, prefab)
    second = next(e for e in _members(level, mine) if _position(level, e) == 20.0)
    _set_position(level, second, "X", "99.000000")
    text = _describe(level, mine)
    assert _changes(text)["modified"] == 1 and _changes(text)["orphans"] == 0 and f"Member {second}" in text, text

    other = _instantiate(level, prefab)
    gone = next(e for e in _members(level, other) if _position(level, e) == 20.0)
    level.ok(f"DeleteEntity -Scene {level.scene} -Id {gone}")
    level.ok(f"ApplyOverrides -Scene {level.scene} -Id {other}", allow_disk=True)

    text = _describe(level, mine)
    assert _orphans(level, mine) == 1 and _changes(text)["orphans"] == 1 and _changes(text)["modified"] == 0, text
    assert re.search(r"^Orphan \w+ Transform\.Transform/Position/X = ", text, re.M) or re.search(r"^Orphan .*Position/X", text, re.M), text
    level.ok(f"RemoveOrphanOverrides -Scene {level.scene} -Id {mine}")
    assert _changes(_describe(level, mine))["total"] == 0


def test_a_member_of_a_nested_instance_answers_for_the_instance_placed_in_the_level(level, level_files_restored):
    """A prefab holding an instance: its inner child, overridden, is described under the outer instance, with its two-element path."""
    inner = _make_prefab(level, with_child=True)
    holder = level.new_entity()
    level.ok(f"AddComponent -Scene {level.scene} -Id {holder} -Component {_component_guid(level, 'Transform')}")
    nested = f"7E57{next(level._ids):04X}"
    level.ok(f"InstantiatePrefab -Scene {level.scene} -Id {nested} -Prefab {inner} -Folder 0 -Parent {holder}")
    asset, lib, parent = _new_asset(level)
    level.ok(f"MakePrefab -Scene {level.scene} -Id {holder} -Library {lib} -Asset {asset} -Parent {parent}", allow_disk=True)
    placed = _instantiate(level, asset[:16])

    deep = next(e for e, a in _members(level, placed).items() if a.count("/") == 1)
    _set_position(level, deep, "X", "42.000000")
    text = _describe(level, deep)
    assert re.search(rf"^Instance {placed} ", text, re.M) and f"Asked {deep}" in text, text
    assert re.search(rf'^Member {deep} ".*" \w+/\w+$', text, re.M), text
    assert _changes(text)["modified"] == 1 and re.search(r"-> 42", text), text


def test_the_prefab_of_an_instance_cannot_be_changed_by_a_command(level):
    """The prefab row of the Inspector is a read-only resource row (no picker, no clear, no drop, only the edit menu). The reference is not reachable by a command
    either: SetProperty on the instance's prefab (it used to abort the editor), and AddComponent / RemoveComponent of the prefab instance, are refused, and the
    instance stays an instance of its prefab."""
    prefab = _make_prefab(level, with_child=True)
    other = _make_prefab(level)
    root = _instantiate(level, prefab)
    first_line = lambda: level.cmd(f"ListPrefabOverrides -Scene {level.scene} -Id {root}").splitlines()[0]
    assert prefab in first_line().upper()

    assert "bookkeeping" in level.cmd(f"SetProperty -Scene {level.scene} -Id {root} -Component EditorPrafabInstance -Path {quote('EditorPrafabInstance/Prefab')}"
                                      f" -TypeGuid 0 -Before {quote(prefab)} -After {quote(other)}")
    assert "bookkeeping" in level.cmd(f"RemoveComponent -Scene {level.scene} -Id {root} -Component EditorPrafabInstance")
    assert "bookkeeping" in level.cmd(f"AddComponent -Scene {level.scene} -Id {level.new_entity()} -Component EditorPrafabInstance")
    assert prefab in first_line().upper() and other not in first_line().upper()
    assert _changes(_describe(level, root))["total"] == 0


# ---- a property that cannot be reverted ----------------------------------------------------------------------------------------------------------

_TRANSLATION = "PhysicsDynamics/Constraints/Translation/{}"


def _set_bool(level, entity: str, path: str, value: str) -> None:
    dynamics = _component_guid(level, "PhysicsDynamics")
    before = "false" if value == "true" else "true"
    level.ok(f"SetProperty -Scene {level.scene} -Id {entity} -Component {dynamics} -Path {quote(path)} -TypeGuid D739B4EF -Before {before} -After {value}")


def _get(level, entity: str, path: str) -> str:
    return level.cmd(f"GetProperty -Scene {level.scene} -Id {entity} -Component {_component_guid(level, 'PhysicsDynamics')} -Path {quote(path)}")


def test_a_group_of_bools_overridden_on_an_instance_reverts_axis_by_axis(level):
    """Constraints/Translation is a row of three checkboxes (a vector3 group of bool): each axis is its own override. The popup's row icon (RevertOverride with the
    value the report printed) puts the prefab's value back, removes the override from the recipe, and Undo brings both back."""
    transform, dynamics = _component_guid(level, "Transform"), _component_guid(level, "PhysicsDynamics")
    root = level.new_entity()
    level.ok(f"AddComponent -Scene {level.scene} -Id {root} -Component {transform}")
    level.ok(f"AddComponent -Scene {level.scene} -Id {root} -Component {dynamics}")
    asset, lib, parent = _new_asset(level)
    level.ok(f"MakePrefab -Scene {level.scene} -Id {root} -Library {lib} -Asset {asset} -Parent {parent}", allow_disk=True)
    placed = _instantiate(level, asset[:16])

    for axis in "XYZ":
        _set_bool(level, placed, _TRANSLATION.format(axis), "true")
    text = _describe(level, placed)
    assert _changes(text)["modified"] == 3 and _changes(text)["added"] == 0, text
    for axis in "XYZ":
        assert re.search(rf"^    {re.escape(_TRANSLATION.format(axis))}: false -> true$", text, re.M), text

    for axis in "XYZ":                                           # what the popup's icon of each row runs
        level.ok(f"RevertOverride -Scene {level.scene} -Id {placed} -Component {dynamics} -Path {quote(_TRANSLATION.format(axis))} -TypeGuid D739B4EF -Before true -After false")
        assert _get(level, placed, _TRANSLATION.format(axis)) == "false"
    assert _changes(_describe(level, placed))["total"] == 0
    assert "Constraints" not in level.cmd(f"ListPrefabOverrides -Scene {level.scene} -Id {placed}"), "the recipe holds no override of it any more"

    for axis in "ZYX":
        level.cmd("Undo")
    assert [_get(level, placed, _TRANSLATION.format(a)) for a in "XYZ"] == ["true"] * 3
    assert _changes(_describe(level, placed))["modified"] == 3


def test_the_properties_of_a_component_the_instance_added_are_not_overrides_to_revert(level):
    """A component the prefab does not have is the instance's own: its properties have no prefab value to go back to, so they are not listed as modified (the row says
    Added, its icon removes the component), and the Inspector draws no revert marker on them (m_AddedComponents, read by the override check)."""
    prefab = _make_prefab(level)
    placed = _instantiate(level, prefab)
    level.ok(f"AddComponent -Scene {level.scene} -Id {placed} -Component {_component_guid(level, 'PhysicsDynamics')}")
    _set_bool(level, placed, _TRANSLATION.format("X"), "true")

    text = _describe(level, placed)
    assert _changes(text)["added"] == 1 and _changes(text)["modified"] == 0 and re.search(r"^  Added PhysicsDynamics$", text, re.M), text
    assert "Modified PhysicsDynamics" not in text, text

    level.ok(f"RemoveComponent -Scene {level.scene} -Id {placed} -Component {_component_guid(level, 'PhysicsDynamics')}")
    assert _changes(_describe(level, placed))["total"] == 0
    level.cmd("Undo")
    assert _get(level, placed, _TRANSLATION.format("X")) == "true" and _changes(_describe(level, placed))["added"] == 1
