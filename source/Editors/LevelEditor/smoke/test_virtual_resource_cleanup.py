"""A compile that no longer makes a virtual resource leaves it alone: a geometry whose imported materials are turned off keeps its generated
Material Instances and Textures (descriptors in Descriptors/, with whatever the user edited), but nothing lists them any more, so they are
not compiled. Turned on again, the same resources are used. A virtual resource nothing lists at startup is kept and not compiled either.
(library_db::m_Chain, dependencies/xresource_pipeline_v2/source/editor/xresource_editor_virtual_chain.h)
The geometry is made by the test from a model it writes (two plain-colored materials); the project guard removes its descriptor.
"""
import re
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


def test_turning_the_import_off_keeps_what_it_made_unused_and_on_uses_it_again(editor, geometry):
    lib, asset = geometry

    _compile(editor, asset, True)
    made = _children(editor, lib, asset)
    assert len(made) == 2, f"one Material Instance per material of the model: {made}"
    folders = [_folder(PROJECT / "Descriptors", "MaterialInstance", g[:16]) / f"{int(g[:16], 16):X}.desc" for g in made]
    assert all(f.is_dir() for f in folders)
    compiled = [_folder(PROJECT / "Cache/Resources/Platforms/WINDOWS", "MaterialInstance", g[:16]) / f"{int(g[:16], 16):X}" for g in made]
    assert all(c.exists() for c in compiled), "its instances were compiled after it"
    stamps = [c.stat().st_mtime_ns for c in compiled]

    _compile(editor, asset, False)
    assert all(f.is_dir() for f in folders), "unused, they stay on disk with their edits"
    assert sorted(_children(editor, lib, asset)) == sorted(made), "and stay the children of the geometry"
    (folders[0] / "Descriptor.txt").touch()
    time.sleep(5)
    while "Compiling=0 Waiting=0" not in editor.cmd("CompileStatus"):
        time.sleep(0.5)
    assert [c.stat().st_mtime_ns for c in compiled] == stamps, "an unused virtual resource is not compiled, not even when it changes"

    _compile(editor, asset, True)
    assert sorted(_children(editor, lib, asset)) == sorted(made), "the same resources are used again (the guids come from the geometry and the material names)"
    assert editor.alive()


def test_a_recompile_that_makes_the_same_resources_keeps_them_listed_once(editor, geometry):
    lib, asset = geometry
    _compile(editor, asset, True)
    made = _children(editor, lib, asset)
    _compile(editor, asset, True)
    assert sorted(_children(editor, lib, asset)) == sorted(made), "neither removed nor listed twice"


def test_at_startup_a_virtual_resource_no_resource_lists_is_kept_and_not_compiled(editor):
    """Left over while no editor ran (or the user's own edit of one the model stopped using): the scan counts who lists each virtual resource
    (library_db::m_Chain) and one that nothing lists stays on disk, uncompiled."""
    source = PROJECT / "Descriptors/Texture/93/EB/D28D2B241BAFEB93.desc"      # the atlas of the example font: a virtual resource
    assert (source / "Info.txt").exists(), "the atlas of the example font is in Descriptors (moved from Cache/Descriptors by the editor at startup)"
    guid = "%015X1" % secrets.randbits(60)
    folder = _folder(PROJECT / "Descriptors", "Texture", guid) / f"{int(guid, 16):X}.desc"
    compiled = _folder(PROJECT / "Cache/Resources/Platforms/WINDOWS", "Texture", guid) / f"{int(guid, 16):X}"
    folder.mkdir(parents=True)
    old = source.name[:-len(".desc")]
    for f in ("Info.txt", "Descriptor.txt"):
        text = (source / f).read_text(errors="replace")
        (folder / f).write_text(text.replace(f"#{old} ", f"#{int(guid, 16):X} ").replace(f"#{old.zfill(16)} ", f"#{int(guid, 16):X} "))
    assert f"#{int(guid, 16):X} " in (folder / "Info.txt").read_text(), "the planted texture has its own guid"
    try:
        editor.stop()
        editor.start()
        deadline = time.time() + 120
        while time.time() < deadline and "Compiling=0 Waiting=0" not in editor.cmd("CompileStatus"):
            time.sleep(0.5)
        assert folder.exists(), "the virtual resource no resource lists is kept (it may hold the user's edits)"
        assert not compiled.exists(), "and it is not compiled"
        assert source.exists(), "one that is listed stays"
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_a_virtual_descriptor_in_the_old_cache_folder_moves_to_descriptors_at_startup(editor):
    """Virtual resources used to keep their descriptors in Cache/Descriptors: the editor moves each Info.txt and Descriptor.txt to Descriptors/ when it
    opens the library; the data a compiler generated next to them stays in the cache, and a folder with an empty Info.txt is a leftover that is not moved."""
    source = PROJECT / "Descriptors/Texture/93/EB/D28D2B241BAFEB93.desc"
    old    = source.name[:-len(".desc")]
    made   = []
    for index, with_info in enumerate((True, False)):
        guid = "%015X1" % secrets.randbits(60)
        legacy = _folder(PROJECT / "Cache/Descriptors", "Texture", guid) / f"{int(guid, 16):X}.desc"
        legacy.mkdir(parents=True)
        (legacy / "bitmap.png").write_bytes(b"pixels")
        (legacy / "Info.txt").write_text((source / "Info.txt").read_text(errors="replace").replace(f"#{old} ", f"#{int(guid, 16):X} ") if with_info else "")
        (legacy / "Descriptor.txt").write_text((source / "Descriptor.txt").read_text(errors="replace"))
        made.append((legacy, _folder(PROJECT / "Descriptors", "Texture", guid) / f"{int(guid, 16):X}.desc", with_info))
    try:
        editor.stop()
        editor.start()
        for legacy, moved, with_info in made:
            assert (legacy / "bitmap.png").exists(), "what the compiler generated stays in the cache"
            if with_info:
                assert (moved / "Info.txt").exists() and (moved / "Descriptor.txt").exists(), "the descriptor moved to Descriptors"
                assert not (legacy / "Info.txt").exists() and not (legacy / "Descriptor.txt").exists()
            else:
                assert not moved.exists(), "a leftover with an empty Info.txt is not a resource: it is not moved"
    finally:
        for legacy, moved, _ in made:
            shutil.rmtree(legacy, ignore_errors=True)
            shutil.rmtree(moved, ignore_errors=True)


def test_a_generated_resource_is_virtual_and_its_owner_is_not(editor, geometry):
    """What the pickers go by (library_db::IsVirtual): they never list a virtual resource, only its owner assigns it."""
    lib, asset = geometry
    _compile(editor, asset, True)
    made = _children(editor, lib, asset)
    assert made and all("Virtual: yes" in editor.cmd(f"DescribeAsset -Library {lib} -Asset {g}") for g in made)
    assert "Virtual: no" in editor.cmd(f"DescribeAsset -Library {lib} -Asset {asset}")


def test_removing_the_unused_ones_takes_them_away_and_undo_brings_them_back(editor, geometry):
    """RemoveUnusedImportedResources (xeditor_virtual_resources.h): the resources the geometry no longer makes, with their textures, leave the disk and
    the library; an undo puts the files back as they were and the library loads them again."""
    lib, asset = geometry
    _compile(editor, asset, True)
    made     = _children(editor, lib, asset)
    textures = sorted({t for m in made for t in _children(editor, lib, m)})
    assert made and textures
    folders = [_folder(PROJECT / "Descriptors", "MaterialInstance", g[:16]) / f"{int(g[:16], 16):X}.desc" for g in made] \
            + [_folder(PROJECT / "Descriptors", "Texture", g[:16]) / f"{int(g[:16], 16):X}.desc" for g in textures]
    command = f"ResourceEditorCommand -Asset {asset} -Cmd RemoveUnusedImportedResources"

    assert "nothing is unused" in editor.cmd(command), "what the geometry makes is in use"
    assert all(f.is_dir() for f in folders)

    _compile(editor, asset, False)
    before = {f: {p.name: p.read_bytes() for p in f.iterdir()} for f in folders}
    editor.ok(command)
    assert not any(f.exists() for f in folders), "all of it is gone, the textures of the instances too"
    assert _children(editor, lib, asset) == [], "and the geometry no longer has them as children"

    assert "Undo: done" in editor.cmd(f"ResourceEditorCommand -Asset {asset} -Cmd Undo")
    deadline = time.time() + 15
    while True:
        try:
            after = {f: {p.name: p.read_bytes() for p in f.iterdir()} for f in folders}
            break
        except OSError:                                              # the file watcher has a file open for a moment
            assert time.time() < deadline
            time.sleep(0.3)
    assert after == before, "the files came back as they were"
    assert sorted(_children(editor, lib, asset)) == sorted(made), "and the library has them again"
    assert editor.alive()


def test_the_font_editor_has_the_command_too(editor):
    """The atlases an earlier output mode made stay unused: the font editor takes them away like the geometry editors. The example font uses its atlas."""
    lib = editor.libraries()[0][0]
    font = "5549D8C8E92200013285CB58BB79E1AD"          # Arial, MTSDF (Descriptors/Font/01/00)
    editor.ok(f"OpenResourceEditor -Asset {font} -Library {lib}", timeout=30)
    try:
        command = f"ResourceEditorCommand -Asset {font} -Cmd RemoveUnusedImportedResources"
        editor.cmd(command)                                         # (what an earlier test planted in the library under this font goes: it is unused)
        assert (PROJECT / "Descriptors/Texture/93/EB/D28D2B241BAFEB93.desc/Info.txt").exists(), "the atlas the font makes is in use: it stays"
        assert "nothing is unused" in editor.cmd(command), "and nothing else is left"
    finally:
        editor.cmd(f"CloseResourceEditor -Asset {font}")


def test_apply_import_compressions_sets_the_generated_textures_and_undo_puts_them_back(editor, geometry):
    """ApplyImportCompressions (xmaterial_instance_import_editor.h): the textures a geometry made take the compressions of its ImportMaterials settings
    (a color map: AlbedoCompression, ...); a texture of a constant stays as it is; an undo writes the descriptors back."""
    from test_imported_materials import png
    lib, asset = geometry
    png(ASSET_DIR / "red.png", (200, 30, 30, 255))
    (ASSET_DIR / "model.mtl").write_text(MTL.replace("newmtl red\nKd 0.8 0.1 0.1", "newmtl red\nKd 0.8 0.1 0.1\nmap_Kd red.png"))
    _compile(editor, asset, True)
    command  = f"ResourceEditorCommand -Asset {asset} -Cmd ApplyImportCompressions"
    made     = _children(editor, lib, asset)
    textures = sorted({t for m in made for t in _children(editor, lib, m)})
    paths    = [_folder(PROJECT / "Descriptors", "Texture", g[:16]) / f"{int(g[:16], 16):X}.desc" / "Descriptor.txt" for g in textures]
    def compressions():
        deadline = time.time() + 15
        while True:
            try:
                return sorted(re.search(r'"Texture/Compression"\s+;enum\s+"([A-Z0-9_]+)"', p.read_text())[1] for p in paths)
            except OSError:                                          # the file watcher has a file open for a moment
                assert time.time() < deadline
                time.sleep(0.3)
    start = compressions()
    assert "RGB_BC1" in start, "the color map of the red material is BC1"
    assert "already have" in editor.cmd(command), "the textures were made with the settings"

    editor.ok(f"ResourceEditorCommand -Asset {asset} -Cmd {quote('SetProperty -Path ' + quote('GeomStatic/ImportMaterials/AlbedoCompression') + ' -Value RGB_BC7')}")
    editor.ok(command)
    changed = compressions()
    assert "RGB_BC1" not in changed and changed.count("RGBA_BC7") == start.count("RGBA_BC7") + 1, "only the color map took the new compression; the textures of constants stayed"

    assert "Undo: done" in editor.cmd(f"ResourceEditorCommand -Asset {asset} -Cmd Undo")       # the last command is the apply
    assert compressions() == start, "the descriptors came back as they were"
    assert "Undo: done" in editor.cmd(f"ResourceEditorCommand -Asset {asset} -Cmd Undo")       # then the setting
    assert editor.alive()
