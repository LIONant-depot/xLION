"""Live update of prefab instances (documentation/Editors/prefabs_plan.md, phase 6).

When a prefab changes, the instances of it in every open editor that is not playing are spawned again from it with their recipes: the overrides stay,
the ids stay (they are derived), so references, the selection and undo still name the members; nothing is written and nothing turns dirty.

* test_prefab_live_update_engine_checks: compiles dependencies/xECSV2/smoke_test_prefab_live.cpp in Debug (asserts on) and runs it - the instances of
  a world spawned again when their prefab changes (on disk, or in memory), keeping their overrides and ids, writing and marking nothing; nested
  prefabs; Apply; a cycle of prefabs does not hang.
* the editor tests: two Levels open with instances of a prefab, the prefab edited and saved in its Prefab Editor; nested prefabs; Apply Overrides
  from one Level reaching the other; a change the Prefab Editor turns down (Undo, Close without saving); a playing Level keeps what it started
  with; a prefab cannot hold a prefab that holds it.
"""
import itertools
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

from conftest import SOCCER_LEVEL, Level
from prefab_bench import REPO, build
from test_prefab_editor import _make, opened      # noqa: F401  (a fixture)
from test_prefabs import _component_guid, _guid_folder, _instantiate, _new_asset, _set_position_x


@pytest.mark.no_editor
def test_prefab_live_update_engine_checks():
    exe = build(debug=True, src=REPO / "dependencies" / "xECSV2" / "smoke_test_prefab_live.cpp")
    r = subprocess.run([str(exe)], capture_output=True, text=True, cwd=exe.parent, timeout=300)
    report = "\n".join(l for l in r.stdout.splitlines() if l.startswith(("STEP", "FAIL", "ALL")) or "CHECK" in l)
    assert r.returncode == 0 and "ALL CHECKS PASSED" in r.stdout, f"{report}\n--- stderr (asserts) ---\n{r.stderr[-3000:]}"
    assert "Assertion" not in r.stderr and "assert" not in r.stderr.lower(), r.stderr[-3000:]


# ---- helpers ----------------------------------------------------------------------------------------------------------------------------------------

def _x(lv, entity: str) -> float:
    return float(re.search(r"Transform/Position/X = (\S+)", lv.describe(entity))[1])


def _members(lv, root: str) -> dict:
    """{member id: address} of an instance, from ListPrefabOverrides."""
    section = lv.cmd(f"ListPrefabOverrides -Scene {lv.scene} -Id {root}").split("Members:\n", 1)[1].split("Orphans:", 1)[0]
    return {m[1]: m[2] for m in re.finditer(r"^\s+(\w+)\s+(\S+)\s*$", section, re.M)}


def _target_of(lv, holder: str) -> str:
    return re.search(r"EntityReference/Target = (.+?)\s+\(TypeGuid", lv.describe(holder))[1]


def _holder(lv, target: str) -> str:
    """An entity of the Level with an EntityReference to target."""
    holder = lv.new_entity()
    reference = _component_guid(lv, "EntityReference")
    lv.ok(f"AddComponent -Scene {lv.scene} -Id {holder} -Component {reference}")
    lv.ok(f"SetEntityReference -Scene {lv.scene} -Id {holder} -Component {reference} -Path EntityReference/Target -AfterScene {lv.scene} -AfterId {target}")
    return holder


def _field(text: str, name: str) -> str:
    return re.search(rf"^{name}=(.*)$", text, re.M)[1].strip()


def _wait_closed(editor, name: str) -> None:
    deadline = time.monotonic() + 15
    while name in [s.name for s in editor.sessions()] and time.monotonic() < deadline:
        time.sleep(0.2)


@pytest.fixture
def other_level(editor, level):
    """A second Level open next to `level` (one that names no Game, with scenes of its own). Its files are put back when the test ends (the tests save it, to see that a live update leaves it clean)."""
    guid, name = next((g, n) for g, n in editor.levels() if g != level.guid and g.lstrip("0").upper() != SOCCER_LEVEL.lstrip("0"))
    folders = [_guid_folder("Level", guid)]
    assert editor.cmd(f"OpenLevel -Level {guid} -Save 0").startswith("Opened Level")
    editor.wait_for(f"{name}\\GetPlayState", r"Building=false", timeout=240)
    scenes = [(m[1], m[2].strip()) for l in editor.cmd(f"{name}\\ListScenes").splitlines() if (m := re.match(r"(\w{16})\s+(.*)", l))]
    lv = Level(editor, guid, name, scenes, itertools.count(0x800))
    assert not {s for s, _ in scenes} & {s for s, _ in level.scenes}, "the two Levels have scenes of their own (a shared scene is read-only in one of them)"
    folders += [_guid_folder("Scene", s) for s, _ in scenes]
    backup = Path(tempfile.mkdtemp(prefix="xlion_live_"))
    for i, folder in enumerate(folders):
        shutil.copytree(folder, backup / str(i))
    yield lv
    try:
        if editor.alive():
            if "Stopped" not in lv.cmd("GetPlayState"):
                lv.cmd("Stop -Keep false")
                editor.wait_for(f"{name}\\GetPlayState", r"PlayState=Stopped", timeout=60)
            lv.cmd("Close -Save 0")
            _wait_closed(editor, name)
    finally:
        for i, folder in enumerate(folders):
            for attempt in range(50):
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


def _saved(lv) -> None:
    assert "rror" not in lv.cmd("Save", allow_disk=True)
    assert not lv.dirty()


# ---- the tests --------------------------------------------------------------------------------------------------------------------------------------

def test_saving_a_prefab_in_its_editor_updates_its_instances_in_every_open_level(level, other_level, opened):
    """The plan's test: two Levels with instances of a prefab; the prefab is edited and saved in its editor; both Levels show the change, keep their overrides, are not dirty (the saved one),
    a reference into an instance member still resolves, the selection is still on its member, and an undo step that names a member still works on it."""
    a, b = level, other_level
    prefab, name = _make(a, children=1)
    root_a = next(e for e, label in a.entities().items() if name in label)     # the entity MakePrefab turned into the instance (named after the prefab)
    child_a = next(iter(_members(a, root_a)))
    before_override = _x(a, child_a)
    _set_position_x(a, child_a, "9.000000")                                 # an override in Level A

    root_b = _instantiate(b, prefab)
    child_b = next(iter(_members(b, root_b)))
    holder = _holder(b, child_b)
    _saved(b)
    target_before = _target_of(b, holder)

    a.ok(f"Select -Scene {a.scene} -Id {child_a}")

    p = opened(prefab, name)
    proot = p.root()
    pchild = next(e for e in p.entities() if e != proot)
    p.set_x(proot, "11.000000")
    p.set_x(pchild, "4.000000")
    added = p.add_child(proot, itertools.count(0x900))
    assert p.cmd("Save", allow_disk=True) == "Saved"

    # Level B: the change, a new member, the same ids, the reference follows the member, nothing to save
    assert _x(b, root_b) == 11.0 and _x(b, child_b) == 4.0
    members_b = _members(b, root_b)
    assert child_b in members_b and len(members_b) == 2, f"the member the prefab gained is there, with a derived id: {members_b}"
    assert not b.dirty(), "a live update is not an edit of the Level"
    assert _target_of(b, holder) != target_before, "the member is a new entity..."
    probe = _holder(b, child_b)
    assert _target_of(b, holder) == _target_of(b, probe), "...and the reference to it is to the new one"

    # Level A: the change where it has no override, the override kept, the selection on its member
    assert _x(a, root_a) == 11.0 and _x(a, child_a) == 9.0
    assert len(_members(a, root_a)) == 2
    level_a = a.cmd("DescribeLevel")                                      # Name\DescribeLevel
    assert _field(level_a, "SelectedEntity") == child_a and _field(level_a, "SelectedEntityLive") == "true", level_a
    a.cmd("Undo")                                                            # the Select
    a.cmd("Undo")                                                            # the override: names the member by its id
    assert _x(a, child_a) == before_override


def test_a_change_to_an_inner_prefab_reaches_the_instances_of_an_outer_prefab(level, other_level, opened):
    """Nested: an instance of an outer prefab that holds the inner one, in a Level and in the outer prefab's own editor, gets a change saved in the inner prefab's editor; neither is dirty."""
    inner, inner_name = _make(level, children=1)
    outer_root = level.new_entity()
    level.ok(f"AddComponent -Scene {level.scene} -Id {outer_root} -Component {_component_guid(level, 'Transform')}")
    outer_name = "PfEd" + inner_name[4:] + "O"
    level.ok(f"RenameEntity -Scene {level.scene} -Id {outer_root} -Name {outer_name}")
    nested = f"7E57{next(level._ids):04X}"
    level.ok(f"InstantiatePrefab -Scene {level.scene} -Id {nested} -Prefab {inner} -Folder 0 -Parent {outer_root}")
    asset, lib, parent = _new_asset(level)
    level.ok(f"MakePrefab -Scene {level.scene} -Id {outer_root} -Library {lib} -Asset {asset} -Parent {parent}", allow_disk=True)
    outer = asset[:16]

    b = other_level
    placed = _instantiate(b, outer)
    _saved(b)
    deep = [m for m, address in _members(b, placed).items() if "/" in address]
    assert len(deep) == 1, f"one member of the nested instance: {_members(b, placed)}"

    po = opened(outer, outer_name)
    in_outer = next(e for e in po.entities() if len(e) == 16)

    pi = opened(inner, inner_name)
    ichild = next(e for e in pi.entities() if e != pi.root())
    pi.set_x(ichild, "6.000000")
    assert pi.cmd("Save", allow_disk=True) == "Saved"

    assert _x(b, deep[0]) == 6.0 and not b.dirty(), "the Level's instance of the outer prefab"
    assert po.x(in_outer) == 6.0 and not po.dirty(), "the outer prefab's own editor"


def test_apply_overrides_in_one_level_reaches_the_other_level_and_its_undo_too(level, other_level):
    """Apply Overrides with no Prefab Editor open writes the prefab: the other instance in the same Level and the instance in the other Level get it at once; the Apply's undo puts both back."""
    a, b = level, other_level
    prefab, _ = _make(a, children=1)
    first = _instantiate(a, prefab)
    second = _instantiate(a, prefab)
    base = _x(a, second)
    placed = _instantiate(b, prefab)
    _saved(b)

    _set_position_x(a, first, "7.500000")
    a.ok(f"ApplyOverrides -Scene {a.scene} -Id {first}", allow_disk=True)
    assert _x(a, second) == 7.5, "the other instance in the same Level"
    assert _x(b, placed) == 7.5 and not b.dirty(), "the instance in the other Level"

    a.cmd("Undo")
    assert _x(a, first) == 7.5, "the instance that applied has its override back"
    assert _x(a, second) == base and _x(b, placed) == base and not b.dirty(), "the others are what the prefab is again"


def test_a_change_the_prefab_editor_turns_down_leaves_the_levels_as_the_file(level, opened):
    """One writer: Apply Overrides into an open Prefab Editor is a step there, and the Level that applied shows it (its own instances). When the Prefab Editor undoes that step, or closes
    without saving it, the Level is brought back to what the file holds (phase 5's open item)."""
    prefab, name = _make(level, children=1)
    p = opened(prefab, name)
    first = _instantiate(level, prefab)
    second = _instantiate(level, prefab)
    base = _x(level, second)

    _set_position_x(level, first, "7.500000")
    level.ok(f"ApplyOverrides -Scene {level.scene} -Id {first}", allow_disk=True)
    assert p.x(p.root()) == 7.5 and p.dirty()
    assert _x(level, second) == 7.5, "the Level shows the change it applied"

    p.cmd("Undo")
    assert not p.dirty()
    assert _x(level, second) == base and _x(level, first) == base, "turned down by Undo: the Level is what the file holds"

    _set_position_x(level, first, "8.500000")                              # once more, and this time the editor is closed without saving
    level.ok(f"ApplyOverrides -Scene {level.scene} -Id {first}", allow_disk=True)
    assert p.x(p.root()) == 8.5 and _x(level, second) == 8.5
    p.close()
    assert _x(level, second) == base and _x(level, first) == base, "turned down by closing without saving: the Level is what the file holds"


def test_a_playing_level_keeps_what_it_started_with(level, other_level, opened):
    """Play worlds are not touched: a Level that is playing keeps its instances as they were; once stopped, it has the change (it reopens from the files)."""
    b = other_level
    prefab, name = _make(b, children=1)                                     # made in the Level that plays: the harness plays only when no editor has unsaved edits
    placed = _instantiate(b, prefab)
    base = _x(b, placed)
    _saved(b)
    assert b.cmd("Play").startswith("Play requested")
    b.ed.wait_for(f"{b.name}\\GetPlayState", r"PlayState=Playing", timeout=120)

    p = opened(prefab, name)
    p.set_x(p.root(), "13.000000")
    assert p.cmd("Save", allow_disk=True) == "Saved"
    assert _x(b, placed) == base, "the running game keeps what it started with"

    assert b.cmd("Stop -Keep false") == "Stop requested"
    b.ed.wait_for(f"{b.name}\\GetPlayState", r"PlayState=Stopped", timeout=60)
    assert _x(b, placed) == 13.0, "stopped: the Level has the change"


def test_a_prefab_cannot_hold_a_prefab_that_holds_it(level, opened):
    """A cycle through other prefabs (A holds B holds A) is refused when it would be made, as a prefab holding itself is."""
    inner, inner_name = _make(level)
    outer_root = level.new_entity()
    level.ok(f"AddComponent -Scene {level.scene} -Id {outer_root} -Component {_component_guid(level, 'Transform')}")
    level.ok(f"InstantiatePrefab -Scene {level.scene} -Id 7E57{next(level._ids):04X} -Prefab {inner} -Folder 0 -Parent {outer_root}")
    asset, lib, parent = _new_asset(level)
    level.ok(f"MakePrefab -Scene {level.scene} -Id {outer_root} -Library {lib} -Asset {asset} -Parent {parent}", allow_disk=True)
    outer = asset[:16]

    p = opened(inner, inner_name)
    reply = p.cmd(f"InstantiatePrefab -Scene {p.guid} -Id {7:08X} -Prefab {outer} -Folder 0 -Parent {p.root()}")
    assert "cannot hold an instance of itself" in reply and "nests it" in reply, reply
    assert len(p.entities()) == 1, "nothing was made"
