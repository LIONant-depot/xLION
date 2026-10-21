"""The Material Instance editor's parameter commands (documentation/material_contract.md section 6; plugins/xmaterial_instance.plugin/source/Editor/xmaterial_instance_editor.h):
SetOverride, ClearOverride, SetParent, SetMaterial (what was set carries over by id, then by name) and ListOverrides (default / parent / here / orphan), every one of them
undoable and redoable.

The editor runs on a small project of its own, made in Build/material_instance_editor by the same program that makes the compiler test's (smoke_test_instance.cpp): the layout and
template of two materials as their compiler leaves them, and a few instances. Nothing of example.lionprj is opened and nothing is ever saved. Windows only.
"""
import os
import re
import shutil
import subprocess

import pytest

import harness
from harness import REPO, Editor
from test_material_instance_params import build, run

pytestmark = [pytest.mark.no_editor, pytest.mark.skipif(os.name != "nt", reason="the project is made with a Windows build of the fixture program")]

ROOT = REPO / "Build" / "material_instance_editor"
INSTANCES = {"MI_Red": 0x1001, "MI_RedRough": 0x1003, "MI_Old": 0x1005, "MI_Orphan": 0x1007, "MI_CycA": 0x1009, "MI_CycB": 0x100B}
ROUGH, TINT, ALBEDO = "0000000000000020", "0000000000000010", "000000000000006E"

INFO = """[ DescriptorVersion ]
{ Major:d  Minor:d }
//-------  -------
     1        0

// New Types
< s32:d u32:g s16:C u16:H s8:c u8:h f32:f f64:F string:s wstring:S u64:G s64:D bool:c full_guid:GG enum:s >

[ xProperties : 5 ]
{ Name:s                        Value:?                                        }
//----------------------------  ----------------------------------------------
  "Info/Name"                   ;string    "%s"
  "Info/Comment"                ;string    ""
  "Info/Details/GUID"           ;full_guid #%X #%s
  "Info/Details/RscLinks[]"     ;s64       1
  "Info/Details/RscLinks[G:0]"  ;full_guid #%X #C4D90C5F0CC43021
"""
LIBRARY, FOLDER = 0xADEB2E3BF97B6E77, 0x5001


def make_project(exe):
    if ROOT.exists():
        shutil.rmtree(ROOT)
    ROOT.mkdir(parents=True)
    assert run(exe, "fixture", ROOT).returncode == 0
    project = ROOT / "t.lionprj"

    shutil.copytree(REPO / "example.lionprj" / "Project.config", project / "Project.config")
    library = project / "Project.config" / "Library.config.txt"
    text = library.read_text().replace("#ADEB2E3BF97B6E03", "#ADEB2E3BF97B6E77")
    text = re.sub(r'("Library/Path"\s+;wstring ")[^"]*"', lambda m: m[1] + str(project).replace("\\", "\\\\") + '"', text)
    library.write_text(text)

    (project / "Cache").mkdir(exist_ok=True)
    done = subprocess.run(["cmd", "/c", "mklink", "/J", str(project / "Cache" / "Plugins"), str(REPO / "example.lionprj" / "Cache" / "Plugins")], capture_output=True, text=True)
    assert done.returncode == 0, done.stdout + done.stderr

    def info(kind, name, guid, parent):
        folder = project / "Descriptors" / kind / f"{guid & 0xff:02X}" / f"{(guid >> 8) & 0xff:02X}" / f"{guid:X}.desc"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "info.txt").write_text(INFO % (name, guid, "C4D90C5F0CC43021" if kind == "Folder" else "B673C5DA4A4A70AD", parent))

    info("Folder", "Test", FOLDER, LIBRARY)
    for name, guid in INSTANCES.items():
        info("MaterialInstance", name, guid, FOLDER)
    return project


@pytest.fixture(scope="module")
def ed():
    exe = build()
    project = make_project(exe)
    editor = Editor(harness.DEFAULT_EXE, args=[project], log_dir=ROOT / "logs")
    editor.start()
    try:
        yield editor
    finally:
        editor.stop()
        os.rmdir(project / "Cache" / "Plugins")           # the junction only, never what it points at
        shutil.rmtree(ROOT, ignore_errors=True)


def open_instance(ed, name):
    ed.ok(f"OpenResourceEditor -Asset {INSTANCES[name]:016X}B673C5DA4A4A70AD -Library {ed.libraries()[0][0]}", timeout=60)
    assert name in {s.name for s in ed.sessions()}, name


def rows(ed, name):
    """{id: (parameter name, type, value, where)} from ListOverrides."""
    out = {}
    for line in ed.cmd(f"{name}\\ListOverrides").splitlines():
        m = re.match(r"([0-9A-F]{16})  (.+?)  (\w+)  (.+?)  (default|here|parent .+|orphan.*)$", line)
        if m:
            out[m[1]] = (m[2], m[3], m[4], m[5])
    return out


def dirty(ed, name):
    return next(s.dirty for s in ed.sessions() if s.name == name)


def undo_redo(ed, name, change, after, before):
    """Runs the command, checks the state it makes, undoes it (the state before comes back), redoes it (the state after comes back), and undoes it again: the next test starts
    from the state this one found."""
    ed.ok(f"{name}\\{change}")
    assert after(rows(ed, name)), f"after {change}: {rows(ed, name)}"
    assert ed.cmd(f"{name}\\Undo") == "Undo: done"
    assert before(rows(ed, name)), f"after undoing {change}: {rows(ed, name)}"
    assert ed.cmd(f"{name}\\Redo") == "Redo: done"
    assert after(rows(ed, name)), f"after redoing {change}: {rows(ed, name)}"
    assert ed.cmd(f"{name}\\Undo") == "Undo: done"


def test_list_overrides_says_where_each_value_comes_from(ed):
    open_instance(ed, "MI_Red")
    r = rows(ed, "MI_Red")
    assert r[TINT] == ("Tint", "COLOR", "1, 0, 0, 1", "here")
    assert r[ROUGH] == ("Roughness", "FLOAT", "0.5", "default")
    assert r[ALBEDO] == ("SamplerAlbedo", "TEXTURE", "0000000000007003", "default")     # a texture the material exposes the old way is a parameter too

    open_instance(ed, "MI_RedRough")
    r = rows(ed, "MI_RedRough")
    assert r[TINT][3] == "parent MI_Red" and r[TINT][2] == "1, 0, 0, 1" and r[ROUGH][2:] == ("0.9", "here")


def test_set_and_clear_override_undo_and_redo(ed):
    open_instance(ed, "MI_Red")
    assert not dirty(ed, "MI_Red")

    undo_redo(ed, "MI_Red", "SetOverride -Id @Roughness -Value 0.9", lambda r: r[ROUGH][2:] == ("0.9", "here"), lambda r: r[ROUGH][2:] == ("0.5", "default"))
    undo_redo(ed, "MI_Red", f"SetOverride -Id {TINT} -Value \"0.2, 0.3, 0.4\"", lambda r: r[TINT][2:] == ("0.2, 0.3, 0.4, 1", "here"), lambda r: r[TINT][2:] == ("1, 0, 0, 1", "here"))
    undo_redo(ed, "MI_Red", "SetOverride -Id @SamplerAlbedo -Value 7005", lambda r: r[ALBEDO][2:] == ("0000000000007005", "here"), lambda r: r[ALBEDO][2:] == ("0000000000007003", "default"))
    assert dirty(ed, "MI_Red")

    # unset is not set-to-default: a value equal to the default is kept (pinned), ClearOverride is what makes it inherit again
    undo_redo(ed, "MI_Red", "SetOverride -Id @Roughness -Value 0.5", lambda r: r[ROUGH][2:] == ("0.5", "here"), lambda r: r[ROUGH][3] == "default")
    undo_redo(ed, "MI_Red", "ClearOverride -Id @Tint", lambda r: r[TINT][2:] == ("1, 1, 1, 1", "default"), lambda r: r[TINT][3] == "here")

    # what is refused says why and changes nothing (no undo step)
    before = rows(ed, "MI_Red")
    for line, why in (("SetOverride -Id @Nope -Value 1", "not a parameter"), (f"SetOverride -Id {ROUGH} -Value \"1, 2\"", "not a value"), (f"SetOverride -Id {ROUGH} -Value abc", "not a value"),
                      (f"SetOverride -Id {ALBEDO} -Value 0", "not a value"), ("SetOverride -Id 77 -Value 1", "no parameter"), ("ClearOverride -Id @Roughness -Value 1", None)):
        reply = ed.cmd(f"MI_Red\\{line}")
        assert reply and (why is None or why in reply), (line, reply)
    assert rows(ed, "MI_Red") == before


def test_orphans_are_listed_kept_and_removable(ed):
    open_instance(ed, "MI_Orphan")
    r = rows(ed, "MI_Orphan")
    assert r["0000000000000999"][2] == "3" and r["0000000000000999"][3].startswith("orphan"), r
    undo_redo(ed, "MI_Orphan", "ClearOverride -Id 999", lambda r: "0000000000000999" not in r, lambda r: "0000000000000999" in r)


def test_set_parent_inherits_and_refuses_a_cycle(ed):
    open_instance(ed, "MI_Old")
    undo_redo(ed, "MI_Old", f"SetParent -Instance {INSTANCES['MI_Red']:016X}", lambda r: r[TINT][2:] == ("1, 0, 0, 1", "parent MI_Red"), lambda r: r[TINT][3] == "default")
    ed.ok(f"MI_Old\\SetParent -Instance {INSTANCES['MI_Red']:016X}")
    undo_redo(ed, "MI_Old", "SetParent -Instance 0", lambda r: r[TINT][3] == "default", lambda r: r[TINT][3] == "parent MI_Red")
    assert ed.cmd("MI_Old\\Undo") == "Undo: done"

    open_instance(ed, "MI_Red")
    assert "cycle" in ed.cmd(f"MI_Red\\SetParent -Instance {INSTANCES['MI_RedRough']:016X}")     # MI_RedRough inherits from MI_Red
    assert "cycle" in ed.cmd(f"MI_Red\\SetParent -Instance {INSTANCES['MI_Red']:016X}")
    assert "could not be read" in ed.cmd("MI_Red\\SetParent -Instance 1234567")

    open_instance(ed, "MI_CycA")
    assert "error: the chain is not valid" in ed.cmd("MI_CycA\\ListOverrides")


def test_set_material_carries_by_id_then_by_name(ed):
    # MI_Red sets Tint (id 10); the other material declares its Tint again under id 11 and keeps Roughness (id 20)
    open_instance(ed, "MI_Red")
    ed.ok("MI_Red\\SetOverride -Id @Roughness -Value 0.7")
    other = "C003"
    ed.ok(f"MI_Red\\SetMaterial -Material {other}")
    r = rows(ed, "MI_Red")
    assert r["0000000000000011"][2:] == ("1, 0, 0, 1", "here"), r                    # by name (and type)
    assert r[ROUGH][2:] == ("0.7", "here"), r                                         # by id
    assert ALBEDO not in r and TINT not in r
    assert ed.cmd("MI_Red\\Undo") == "Undo: done"
    r = rows(ed, "MI_Red")
    assert r[TINT][2:] == ("1, 0, 0, 1", "here") and ALBEDO in r and "0000000000000011" not in r, r
    assert ed.cmd("MI_Red\\Redo") == "Redo: done"
    assert rows(ed, "MI_Red")["0000000000000011"][3] == "here"

    # what the new material has no parameter for stays as an orphan, not dropped
    open_instance(ed, "MI_Old")                                                       # its albedo override (id 6E)
    ed.ok(f"MI_Old\\SetMaterial -Material {other}")
    assert rows(ed, "MI_Old")[ALBEDO][3].startswith("orphan"), rows(ed, "MI_Old")
    assert "compile the material first" in ed.cmd("MI_Old\\SetMaterial -Material C005")
