"""A Mesh's material overrides (Override Materials): what each slot row shows, where its value comes from, and what the override marker (>) reverts to.

Levels a parameter inherits through: the material (and its instances) -> the slot's instance (the geometry's own, or one the entity swaps in) -> a prefab
(when the entity is a prefab instance's) -> the entity. The rows show the value the entity draws with; Source says where it comes from; Override is the
entity's own value as text ("" inherits). OverrideState says what the marker says: overridden or not, whether a prefab is a level, and each revert on
offer (one goes one level up; when the prefab overrides the row too, a second goes past it). An override of a parameter the instance does not have (after
a swap) is kept, shown as not applied, and applies again when the instance has it.
"""
import re
import secrets

from test_prefabs import FOLDER_TYPE, PREFAB_TYPE, _instantiate, _reload, level_files_restored      # noqa: F401  (a fixture of the prefab tests)
from test_scene_render import POLICE_STATION

MI_RED = "5E1CE0A110000003, B673C5DA4A4A70AD"          # an instance of another material (Tint, Roughness, Albedo): no BaseColorFactor


def _mesh(level, entity=None) -> str:
    e = entity or level.new_entity()
    if entity is None:
        level.ok(f"AddComponent -Scene {level.scene} -Id {e} -Component Transform")
        level.ok(f"AddComponent -Scene {level.scene} -Id {e} -Component Mesh")
    level.ok(f'SetProperty -Scene {level.scene} -Id {e} -Component Mesh -Path Mesh/Geom -After "{POLICE_STATION}"')
    level.ok(f"SetProperty -Scene {level.scene} -Id {e} -Component Mesh -Path \"Mesh/Override Materials\" -After true")
    level.ed.wait_for(f"{level.name}\\DescribeEntity -Scene {level.scene} -Id {e}", r"Mesh/Slots\[G:0\]/Parameters\[G:\d+\]/Source = ", timeout=120)
    return e


def _rows(level, e: str, slot: int = 0) -> dict:
    """Row name -> (key, Source, Override) of a slot: a row's address is its key (the parameter's id), not its place."""
    text = level.describe(e)
    rows = {}
    for i, name in re.findall(rf"Mesh/Slots\[G:{slot}\]/Parameters\[G:(\d+)\]/Name = (.*?)  \(", text):
        source   = re.search(rf"Mesh/Slots\[G:{slot}\]/Parameters\[G:{i}\]/Source = (.*?)  \(", text)[1]
        override = re.search(rf"Mesh/Slots\[G:{slot}\]/Parameters\[G:{i}\]/Override = (.*?)  \(", text)
        rows[name] = (int(i), source, override[1] if override else "")
    return rows


def _set(level, e: str, path: str, value: str) -> None:
    level.ok(f'SetProperty -Scene {level.scene} -Id {e} -Component Mesh -Path "{path}" -After "{value}"')


def _state(level, e: str, path: str) -> dict:
    text = level.cmd(f'OverrideState -Scene {level.scene} -Id {e} -Component Mesh -Path "{path}"')
    assert text.startswith("OverrideState: "), text
    return {"overridden": "Overridden=true" in text, "prefab": "Prefab=true" in text
           , "reverts": re.findall(r'^Revert "(.*?)": -Path (\S+) -After "(.*)"$', text, re.M), "text": text}


def test_a_row_inherits_overrides_and_reverts(level):
    e = _mesh(level)
    rows = _rows(level, e)
    assert "BaseColorFactor" in rows and all(s == "material instance" for _, s, _ in rows.values()), rows
    i = rows["BaseColorFactor"][0]
    row = f"Mesh/Slots[G:0]/Parameters[G:{i}]"
    assert re.search(r"Mesh/Slots\[G:0\]/Material = [0-9A-F]{16}, ", level.describe(e)), "the Material row shows the geometry's own instance, not none"
    assert not _state(level, e, "Mesh/Slots[G:0]/Material")["overridden"]

    _set(level, e, f"{row}/Value/G", "0.05")                        # the inspector's edit of one channel
    assert _rows(level, e)["BaseColorFactor"][1] == "entity"
    assert re.search(r"Mesh/Slots\[G:0\]/Overrides\[\] = 1\b", level.describe(e)), "only the overridden parameter is saved"
    s = _state(level, e, row)
    assert s["overridden"] and not s["prefab"] and [r[0] for r in s["reverts"]] == ["Revert to the material instance"], s["text"]
    assert s["reverts"][0][1] == f"{row}/Override" and s["reverts"][0][2] == "", s["text"]

    _set(level, e, f"{row}/Override", "")                           # the revert the marker does
    assert _rows(level, e)["BaseColorFactor"][1:] == ("material instance", ""), "reverted: the instance's value again"
    assert not _state(level, e, row)["overridden"]
    assert level.cmd("Undo") == "Undone"
    assert _rows(level, e)["BaseColorFactor"][1] == "entity", "the revert is undone like any edit"


def test_an_override_survives_a_swap_and_applies_again(level):
    e = _mesh(level)
    i = _rows(level, e)["BaseColorFactor"][0]
    _set(level, e, f"Mesh/Slots[G:0]/Parameters[G:{i}]/Override", "1, 0, 0, 1")

    _set(level, e, "Mesh/Slots[G:0]/Material", MI_RED)
    rows = _rows(level, e)
    assert {"Tint", "Roughness", "Albedo"} <= set(rows), rows
    assert rows["BaseColorFactor"][1].startswith("not applied"), "kept, shown, not applied: the instance has no such parameter"
    orphan = f"Mesh/Slots[G:0]/Parameters[G:{rows['BaseColorFactor'][0]}]"
    assert [r[0] for r in _state(level, e, orphan)["reverts"]] == ["Clear (not applied: the material has no such parameter)"]
    s = _state(level, e, "Mesh/Slots[G:0]/Material")
    assert s["overridden"] and s["reverts"][0][0] == "Revert to the geometry's material instance", s["text"]

    _set(level, e, s["reverts"][0][1], s["reverts"][0][2])          # back to the geometry's instance
    rows = _rows(level, e)
    assert rows["BaseColorFactor"][1:] == ("entity", "1, 0, 0, 1"), "the kept override applies again"
    assert not _state(level, e, "Mesh/Slots[G:0]/Material")["overridden"]


def _make_mesh_prefab(level) -> str:
    e = _mesh(level)
    lib = level.ed.libraries()[0][0]
    asset = "%016X" % (secrets.randbits(63) | 1) + PREFAB_TYPE
    level.ok(f"MakePrefab -Scene {level.scene} -Id {e} -Library {lib} -Asset {asset} -Parent {lib}{FOLDER_TYPE}", allow_disk=True)
    return asset[:16]


def test_an_instance_override_follows_its_parameter_when_the_rows_reorder(level, level_files_restored):
    """A prefab instance's override is recorded by the parameter's key: its rows change order (here: another instance swapped in, whose material
    lists other parameters - the override's row moves from 2nd to last) and a save and a load later it is still on the same parameter."""
    inst = _instantiate(level, _make_mesh_prefab(level))
    level.ed.wait_for(f"{level.name}\\DescribeEntity -Scene {level.scene} -Id {inst}", r"Parameters\[G:\d+\]/Source = ", timeout=120)
    rows = _rows(level, inst)
    key = rows["BaseColorFactor"][0]
    before = list(rows).index("BaseColorFactor")
    _set(level, inst, f"Mesh/Slots[G:0]/Parameters[G:{key}]/Override", "0, 1, 0, 1")
    assert f"Parameters[G:{key}]" in level.cmd(f"DescribePrefabOverrides -Scene {level.scene} -Id {inst}"), "recorded by the parameter's key"

    _set(level, inst, "Mesh/Slots[G:0]/Material", MI_RED)
    rows = _rows(level, inst)
    assert list(rows).index("BaseColorFactor") != before and rows["BaseColorFactor"][0] == key, "another place, the same key"
    assert rows["BaseColorFactor"][2] == "0, 1, 0, 1"

    _reload(level)
    level.ed.wait_for(f"{level.name}\\DescribeEntity -Scene {level.scene} -Id {inst}", r"Parameters\[G:\d+\]/Source = ", timeout=120)
    orphan = {k: (s, o) for k, s, o in _rows(level, inst).values()}.get(key)       # (loaded by its key alone: named again by the material that has it)
    assert orphan == ("not applied (the material has no such parameter)", "0, 1, 0, 1"), orphan
    _set(level, inst, "Mesh/Slots[G:0]/Material", _state(level, inst, "Mesh/Slots[G:0]/Material")["reverts"][0][2])
    assert _rows(level, inst)["BaseColorFactor"][1:] == ("entity", "0, 1, 0, 1"), "back on its instance: applied, on the same parameter"


def test_a_prefab_instance_stacks_over_its_prefab(level, level_files_restored):
    e = _mesh(level)
    i = _rows(level, e)["BaseColorFactor"][0]
    row = f"Mesh/Slots[G:0]/Parameters[G:{i}]"
    _set(level, e, f"{row}/Override", "1, 0, 0, 1")                 # the prefab overrides the row
    lib = level.ed.libraries()[0][0]
    asset = "%016X" % (secrets.randbits(63) | 1) + PREFAB_TYPE
    level.ok(f"MakePrefab -Scene {level.scene} -Id {e} -Library {lib} -Asset {asset} -Parent {lib}{FOLDER_TYPE}", allow_disk=True)
    inst = _instantiate(level, asset[:16])
    level.ed.wait_for(f"{level.name}\\DescribeEntity -Scene {level.scene} -Id {inst}", r"Parameters\[G:\d+\]/Source = ", timeout=120)

    s = _state(level, inst, row)
    assert s["prefab"] and not s["overridden"], "the instance inherits the prefab's override: nothing of its own"
    assert _rows(level, inst)["BaseColorFactor"][1:] == ("entity", "1, 0, 0, 1")

    _set(level, inst, f"{row}/Override", "0, 1, 0, 1")              # the instance overrides it again
    s = _state(level, inst, row)
    assert s["overridden"] and [(r[0], r[2]) for r in s["reverts"]] == [("Revert to the prefab", "1, 0, 0, 1"), ("Revert to the material instance", "")], s["text"]

    _set(level, inst, s["reverts"][0][1], s["reverts"][0][2])       # one level up: the prefab's
    assert not _state(level, inst, row)["overridden"]
    assert _rows(level, inst)["BaseColorFactor"][2] == "1, 0, 0, 1"

    _set(level, inst, f"{row}/Override", "")                        # past the prefab: the material instance's
    s = _state(level, inst, row)
    assert s["overridden"] and [r[0] for r in s["reverts"]] == ["Revert to the prefab"], "differs from the prefab (which overrides it): one way back"
