"""A compile that no longer makes a virtual resource removes it: a geometry whose imported materials are turned off loses its
generated Material Instances and Textures, from the resource browser (the geometry's children) and from the disk (Cache/Descriptors,
the compiled data, the log). Turned on again, they come back - and the editor survives the cycle: the library's info map reuses the
slots of the entries it deleted (xcontainer::unordered_lockless_map::FreeData once linked them wrong and the next creations asserted).
The geometry is made by the test from a model it writes (two plain-colored materials); the project guard removes its descriptor.
"""
import secrets
import shutil
import time

import pytest

from harness import REPO, quote

PROJECT     = REPO / "example.lionprj"
ASSET_DIR   = PROJECT / "Assets" / "_smoke_virtual_cleanup"
GEOM_TYPE   = "E5359948C52D26D1"
FOLDER_TYPE = "C4D90C5F0CC43021"

OBJ = """mtllib model.mtl
v 0 0 0
v 1 0 0
v 1 1 0
v 0 1 0
vn 0 0 1
usemtl red
f 1//1 2//1 3//1
usemtl blue
f 1//1 3//1 4//1
"""
MTL = """newmtl red
Kd 0.8 0.1 0.1
newmtl blue
Kd 0.1 0.1 0.8
"""


def _folder(root, type_name: str, guid: str):
    v = int(guid, 16)
    return root / type_name / f"{v & 0xFF:02X}" / f"{(v >> 8) & 0xFF:02X}"


def _children(editor, lib: str, asset: str) -> list[str]:
    text = editor.cmd(f"DescribeAsset -Library {lib} -Asset {asset}")
    return [line.strip() for line in text.split("Children", 1)[1].splitlines()[1:] if line.strip()]


def _compile(editor, asset: str, on: bool) -> None:
    """SetImportMaterials then Compile, and wait until this compile is over (its dependencies file is rewritten, then the queue is idle)."""
    deps = _folder(PROJECT / "Cache/Resources/Logs", "GeomStatic", asset[:16]) / f"{int(asset[:16], 16):X}.log" / "dependencies.txt"
    before = deps.stat().st_mtime_ns if deps.exists() else 0
    editor.ok(f"ResourceEditorCommand -Asset {asset} -Cmd {quote('SetImportMaterials -On ' + ('true' if on else 'false'))}")
    reply = editor.cmd(f"ResourceEditorCommand -Asset {asset} -Cmd Compile", allow_disk=True)
    assert "compile queued" in reply, reply
    deadline = time.time() + 120
    while time.time() < deadline and not (deps.exists() and deps.stat().st_mtime_ns != before):
        time.sleep(0.5)
    assert deps.exists() and deps.stat().st_mtime_ns != before, "the geometry was not compiled"
    while time.time() < deadline and "Compiling=0 Waiting=0" not in editor.cmd("CompileStatus"):
        time.sleep(0.5)


@pytest.fixture
def geometry(editor):
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    (ASSET_DIR / "model.obj").write_text(OBJ)
    (ASSET_DIR / "model.mtl").write_text(MTL)
    lib = editor.libraries()[0][0]
    asset = "%016X" % (secrets.randbits(63) | 1) + GEOM_TYPE
    editor.ok(f"CreateAsset -Library {lib} -Type {GEOM_TYPE} -Asset {asset} -Parent {lib}{FOLDER_TYPE} -Name SmokeVirtualCleanup", allow_disk=True)
    editor.ok(f"OpenResourceEditor -Asset {asset} -Library {lib}", timeout=30)
    for path, value in (("GeomStatic/ImportAsset", r"Assets\_smoke_virtual_cleanup\model.obj"), ("GeomStatic/AllMeshesDetails/Name", "Model"), ("GeomStatic/GI/Mode", "OFF")):
        editor.ok(f"ResourceEditorCommand -Asset {asset} -Cmd {quote(f'SetProperty -Path {quote(path)} -Value {quote(value)}')}")
    try:
        yield lib, asset
    finally:
        editor.cmd(f"CloseResourceEditor -Asset {asset}")
        shutil.rmtree(ASSET_DIR, ignore_errors=True)


def test_turning_the_import_off_removes_what_it_made_and_on_brings_it_back(editor, geometry):
    lib, asset = geometry

    _compile(editor, asset, True)
    made = _children(editor, lib, asset)
    assert len(made) == 2, f"one Material Instance per material of the model: {made}"
    folders = [_folder(PROJECT / "Cache/Descriptors", "MaterialInstance", g[:16]) / f"{int(g[:16], 16):X}.desc" for g in made]
    assert all(f.is_dir() for f in folders)

    _compile(editor, asset, False)
    assert _children(editor, lib, asset) == [], "the geometry no longer lists them"
    assert not any(f.exists() for f in folders), "and they are gone from the disk"

    _compile(editor, asset, True)
    assert sorted(_children(editor, lib, asset)) == sorted(made), "the same resources come back (the guids come from the geometry and the material names)"
    assert editor.alive()


def test_a_recompile_that_makes_the_same_resources_keeps_them_listed_once(editor, geometry):
    lib, asset = geometry
    _compile(editor, asset, True)
    made = _children(editor, lib, asset)
    _compile(editor, asset, True)
    assert sorted(_children(editor, lib, asset)) == sorted(made), "neither removed nor listed twice"


def test_at_startup_a_virtual_resource_no_resource_lists_is_removed(editor):
    """Left over while no editor ran: the scan counts who lists each virtual resource (library_db::m_VirtualRefs) and removes the ones at 0."""
    source = next(p for p in (PROJECT / "Cache/Descriptors/Texture").rglob("*.desc") if (p / "Info.txt").exists() and (p / "Info.txt").stat().st_size)
    guid = "%015X1" % secrets.randbits(60)
    folder = _folder(PROJECT / "Cache/Descriptors", "Texture", guid) / f"{int(guid, 16):X}.desc"
    folder.mkdir(parents=True)
    old = source.name[:-len(".desc")]
    for f in ("Info.txt", "Descriptor.txt"):
        text = (source / f).read_text(errors="replace")
        (folder / f).write_text(text.replace(f"#{old} ", f"#{int(guid, 16):X} ").replace(f"#{old.zfill(16)} ", f"#{int(guid, 16):X} "))
    assert f"#{int(guid, 16):X} " in (folder / "Info.txt").read_text(), "the planted texture has its own guid"
    try:
        editor.stop()
        editor.start()
        assert not folder.exists(), "the virtual resource no resource lists is gone"
        assert source.exists(), "one that is listed stays"
    finally:
        shutil.rmtree(folder, ignore_errors=True)
