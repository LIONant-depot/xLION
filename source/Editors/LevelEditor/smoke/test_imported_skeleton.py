"""A skin with ImportSkeletonAndAnimation on (GeomSkin/ImportSkeletonAndAnimation, the default) makes a virtual Skeleton and a virtual Anim Package of
its model, like the imported materials, and its SkeletonRef and AnimationRef (read-only in the editor) are those two: the skin compiler binds its bones with the bone manifest it builds itself (xskeleton_merge.h, the
Skeleton compiler's own code), since the skeleton compiles after it. Here the three compilers run in the pipeline's order on a project of
their own (the example project's Walking.fbx): the skin binds without a compiled skeleton, the generated skeleton and package compile on
it, and a second compile makes the same resources. No editor: the
read-only rows and the preview's animation (the AnimationRef) are drawn by the skin editor.
(The compilers are their own executables: build plugins/xgeom_skin.plugin, xskeleton.plugin and xanim_package.plugin first when they changed.)
"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from harness import REPO, compiler_exe

pytestmark = pytest.mark.no_editor

SKIN_GUID = "1234567890AB0007"
MODEL     = REPO / "example.lionprj/Assets/WalkingSkin/Walking.fbx"

HEADER = """[ DescriptorVersion ]
{ Major:d  Minor:d }
     1        0

< s32:d u32:g s16:C u16:H s8:c u8:h f32:f f64:F string:s wstring:S u64:G s64:D bool:c full_guid:GG enum:s >

"""


def folder(type_name: str, guid: str) -> str:
    v = int(guid, 16)
    return f"{type_name}\\{v & 0xFF:02X}\\{(v >> 8) & 0xFF:02X}\\{v:X}"


@pytest.fixture
def project(tmp_path):
    if not MODEL.exists():
        pytest.fail(f"the example project's model is missing: {MODEL}")
    prj = tmp_path / "t.lionprj"
    (prj / "Assets/WalkingSkin").mkdir(parents=True)
    shutil.copy(MODEL, prj / "Assets/WalkingSkin/Walking.fbx")
    desc = prj / "Descriptors" / (folder("GeomSkin", SKIN_GUID) + ".desc")
    desc.mkdir(parents=True)
    (desc / "Descriptor.txt").write_text(HEADER + """[ xProperties : 4 ]
{ Name:s  Value:? }
  "GeomSkin/ImportAsset" ;wstring "Assets\\\\WalkingSkin\\\\Walking.fbx"
  "GeomSkin/bMergeAllMeshes" ;bool 1
  "GeomSkin/AllMeshesDetails/Name" ;string "Walking"
  "GeomSkin/ImportMaterials/bImport" ;bool 0
""")
    (prj / "Cache/Resources/Platforms").mkdir(parents=True)
    return prj


def compile_one(prj: Path, plugin: str, descriptor: str) -> str:
    exe = compiler_exe(plugin)
    if not exe.exists():
        pytest.fail(f"build the {plugin} compiler first: {exe}")
    run = subprocess.run([str(exe), "-PROJECT", str(prj), "-OPTIMIZATION", "O1", "-DEBUG", "D0", "-DESCRIPTOR", descriptor
                         , "-OUTPUT", str(prj / "Cache/Resources/Platforms")], capture_output=True, text=True, timeout=300)
    out = run.stdout + run.stderr
    assert "[COMPILATION_SUCCESS]" in out, f"{plugin}: {out[-3000:]}"
    return out


def virtual(prj: Path, type_name: str) -> list[Path]:
    return [p.parent for p in (prj / "Descriptors" / type_name).rglob("Descriptor.txt")]


def test_the_skin_makes_its_skeleton_and_animations_and_binds_to_the_same_bones(project):
    out = compile_one(project, "xgeom_skin", "Descriptors\\" + folder("GeomSkin", SKIN_GUID) + ".desc")

    skeletons, packages = virtual(project, "Skeleton"), virtual(project, "AnimPackage")
    assert len(skeletons) == 1 and len(packages) == 1, "one generated skeleton and one generated anim package"
    skeleton_guid = skeletons[0].name.removesuffix(".desc")
    package_guid  = packages[0].name.removesuffix(".desc")
    assert f"SkeletonRef {skeleton_guid} AnimationRef {package_guid}" in out, "the compiled skin carries the guids of the generated skeleton and package"
    package_text  = (packages[0] / "Descriptor.txt").read_text()
    assert "Walking.fbx" in (skeletons[0] / "Descriptor.txt").read_text()
    assert "Walking.fbx" in package_text
    assert re.search(rf'"AnimPackage/SkeletonRef"\s+;full_guid\s+#{skeleton_guid} ', package_text), "the package is on the skin's skeleton"

    # Both are children of the skin in the asset browser
    for f in (skeletons[0], packages[0]):
        assert f"#{SKIN_GUID} " in (f / "Info.txt").read_text()

    # The pipeline's order: the skeleton (its manifest), then the package on it
    compile_one(project, "xskeleton", "Descriptors\\" + str(skeletons[0].relative_to(project / "Descriptors")))
    compile_one(project, "xanim_package", "Descriptors\\" + str(packages[0].relative_to(project / "Descriptors")))

    manifest = next((project / "Cache/Resources/Logs/Skeleton").rglob("AnimPackage.txt")).read_text()
    bones    = re.findall(r'"bone_manifest/Bones\[G:\d+\]/Name"\s+;string\s+"([^"]*)"', manifest)
    assert len(bones) > 10, "the skeleton of the model, every bone"

    # The skin compiler's own manifest (the same code) bound the skin: the skin compiled, so every weighted bone was found in it; compiling
    # the skin again with the generated skeleton now on disk makes the same virtual resources (nothing else appears)
    compile_one(project, "xgeom_skin", "Descriptors\\" + folder("GeomSkin", SKIN_GUID) + ".desc")
    assert len(virtual(project, "Skeleton")) == 1 and len(virtual(project, "AnimPackage")) == 1


def test_the_edits_of_the_generated_skeleton_and_package_survive_a_recompile(project):
    """Rule 3 of documentation/Editors/virtual_resources_plan.md: a compile updates only what the skin owns: the skeleton's import file, the package's skeleton and file."""
    skin = "Descriptors\\" + folder("GeomSkin", SKIN_GUID) + ".desc"
    compile_one(project, "xgeom_skin", skin)
    skeleton, package = virtual(project, "Skeleton")[0] / "Descriptor.txt", virtual(project, "AnimPackage")[0] / "Descriptor.txt"
    skeleton_guid = skeleton.parent.name.removesuffix(".desc")

    text, n = re.subn(r'("Skeleton/PreTransform/Scale/X"\s+;f32\s+)#3F800000', r"\1#40000000", skeleton.read_text())     # the columns are as wide as the longest name: not a fixed text
    assert n == 1, "the generated skeleton has the default scale"
    skeleton.write_text(text)
    package.write_text(re.sub(r'("AnimPackage/SkeletonRef"\s+;full_guid\s+)#[0-9A-F]+', r"\1#1234", package.read_text()))
    skeleton_stamp = skeleton.stat().st_mtime_ns

    compile_one(project, "xgeom_skin", skin)
    text = skeleton.read_text()
    assert re.search(r'"Skeleton/PreTransform/Scale/X"\s+;f32\s+#40000000', text), "the pre-transform is the user's"
    assert skeleton.stat().st_mtime_ns == skeleton_stamp, "the skeleton was not written: nothing of it changed"
    assert re.search(rf'"AnimPackage/SkeletonRef"\s+;full_guid\s+#{skeleton_guid} ', package.read_text()), "the skeleton of the package is the skin's"


def size_of(out: str) -> list[float]:
    return [float(v) for v in re.search(r"Size (\S+) (\S+) (\S+)", out).groups()]


def test_the_skeleton_is_the_master_the_skin_takes_its_scale(project):
    """The skin has no transform or units of its own: a new skeleton has no pre-transform (the mesh in the model's units), and the PreTransform the user gives the
    skeleton is what the skin's mesh is compiled in (its bind poses and the mesh agree)."""
    skin = "Descriptors\\" + folder("GeomSkin", SKIN_GUID) + ".desc"
    before = size_of(compile_one(project, "xgeom_skin", skin))
    skeleton = virtual(project, "Skeleton")[0] / "Descriptor.txt"
    text = skeleton.read_text()
    assert len(re.findall(r'"Skeleton/PreTransform/Scale/[XYZ]"\s+;f32\s+#3F800000', text)) == 3, "a new skeleton: no pre-transform"

    text, n = re.subn(r'("Skeleton/PreTransform/Scale/[XYZ]"\s+;f32\s+)#3F800000', r"\1#3C23D70A", text)       # 0.01: the model is in cm
    assert n == 3
    skeleton.write_text(text)
    after = size_of(compile_one(project, "xgeom_skin", skin))
    assert all(abs(a - b * 0.01) <= b * 0.0002 + 1e-4 for a, b in zip(after, before)), f"the mesh takes the skeleton's scale: {before} -> {after}"


def test_a_skin_that_does_not_import_has_no_generated_resources_and_needs_its_own_skeleton(project):
    desc = project / "Descriptors" / (folder("GeomSkin", SKIN_GUID) + ".desc") / "Descriptor.txt"
    desc.write_text(desc.read_text().replace("xProperties : 4", "xProperties : 5").replace('"GeomSkin/ImportMaterials/bImport" ;bool 0','"GeomSkin/ImportMaterials/bImport" ;bool 0\n  "GeomSkin/ImportSkeletonAndAnimation" ;bool 0'))
    exe = compiler_exe("xgeom_skin")
    run = subprocess.run([str(exe), "-PROJECT", str(project), "-OPTIMIZATION", "O1", "-DEBUG", "D0", "-DESCRIPTOR", "Descriptors\\" + folder("GeomSkin", SKIN_GUID) + ".desc"
                         , "-OUTPUT", str(project / "Cache/Resources/Platforms")], capture_output=True, text=True, timeout=300)
    assert "[COMPILATION_SUCCESS]" not in run.stdout + run.stderr, "no skeleton: the skin does not compile"
    assert "skeleton reference is NULL" in run.stdout + run.stderr
    assert virtual(project, "Skeleton") == [] and virtual(project, "AnimPackage") == [], "and nothing was generated"


def _vec(text: str, pattern: str) -> list[float]:
    m = re.search(pattern + r" (-?[\d.]+) (-?[\d.]+) (-?[\d.]+)", text)
    assert m, f"no {pattern!r} in the compile log: {text[-2000:]}"
    return [float(v) for v in m.groups()]


def _compile_skin_and_skeleton(prj: Path, skin: str) -> dict:
    """The skin, then its skeleton (the pipeline's order): where the mesh is and where the joints of the bind pose are, from the two compile logs."""
    mesh = compile_one(prj, "xgeom_skin", skin)
    skeleton = virtual(prj, "Skeleton")[0]
    joints = compile_one(prj, "xskeleton", "Descriptors\\" + str(skeleton.relative_to(prj / "Descriptors")))
    return {"mesh_size": _vec(mesh, r"\] Size"), "mesh_center": _vec(mesh, r"\] Center"),
            "joint_size": _vec(joints, r"Joints \d+ Size"), "joint_center": _vec(joints, r"Center")}


def test_the_skin_follows_the_pretransform_of_its_generated_skeleton_and_editing_it_back_restores_it(project):
    """The skeleton is the master: its PreTransform moves the bind poses (the Skeleton compiler) and the vertices (the skin compiler) the same way, so the
    skin stays on its bones. Scale 2, 90 degrees about Y and 1 m up: both boxes double, swap X and Z, and rise by 1; the skin's dependencies name the
    skeleton's descriptor (an edit of it compiles the skin again); the edit is the user's (the skin's compile keeps it); and editing it back gives the
    original boxes."""
    skin = "Descriptors\\" + folder("GeomSkin", SKIN_GUID) + ".desc"
    before = _compile_skin_and_skeleton(project, skin)
    skeleton = virtual(project, "Skeleton")[0] / "Descriptor.txt"
    original = skeleton.read_text()
    deps = next((project / "Cache/Resources/Logs/GeomSkin").rglob("dependencies.txt")).read_text().replace("\\\\", "/").lower()
    assert str(skeleton.relative_to(project)).replace("\\", "/").lower() in deps, "the skin compiles again when its skeleton's descriptor changes"

    edited, values = original, (("Scale/X", "40000000"), ("Scale/Y", "40000000"), ("Scale/Z", "40000000"), ("Rotation/Y", "42B40000"), ("Translation/Y", "3F800000"))
    for name, value in values:
        edited, n = re.subn(rf'("Skeleton/PreTransform/{name}"\s+;f32\s+)#[0-9A-F]+', rf"\g<1>#{value}", edited)
        assert n == 1, name
    skeleton.write_text(edited)
    after = _compile_skin_and_skeleton(project, skin)
    kept = skeleton.read_text()                                       # (its columns may be aligned again: the values are what counts)
    assert all(re.search(rf'"Skeleton/PreTransform/{name}"\s+;f32\s+#{value}\b', kept) for name, value in values), "the skin's compile keeps the user's PreTransform"

    def close(a, b, what):
        assert all(abs(x - y) <= 1e-3 + 1e-3 * abs(y) for x, y in zip(a, b)), f"{what}: {a} != {b}"
    for box in ("mesh", "joint"):
        sx, sy, sz = before[f"{box}_size"]
        close(after[f"{box}_size"], [2 * sz, 2 * sy, 2 * sx], f"the {box} box doubles and turns a quarter about Y")
        close([after[f"{box}_center"][1]], [2 * before[f"{box}_center"][1] + 1], f"the {box} box rises by 1 after its scale")
    # the skin stays on its bones: the offset between the two boxes turns and scales with them
    d0 = [m - j for m, j in zip(before["mesh_center"], before["joint_center"])]
    d1 = [m - j for m, j in zip(after["mesh_center"], after["joint_center"])]
    close([abs(d1[0]), d1[1], abs(d1[2])], [2 * abs(d0[2]), 2 * d0[1], 2 * abs(d0[0])], "the mesh keeps its place on the joints")

    skeleton.write_text(original)
    restored = _compile_skin_and_skeleton(project, skin)
    for k in before:
        close(restored[k], before[k], f"editing it back restores the {k}")


# Bone palettes (documentation/Editors/skin_bone_palette_plan.md) ------------------------------------------------------------------------------

def addressing(out: str) -> tuple[int, int, int]:
    m = re.search(r"Skin addressing: (\d+) base-offset clusters, (\d+) palette clusters, (\d+) BoneMap entries", out)
    assert m, f"no addressing line in the compile log: {out[-2000:]}"
    return tuple(int(v) for v in m.groups())


def compiled_skin(prj: Path) -> bytes:
    files = [f for f in (prj / "Cache/Resources/Platforms").rglob("*") if f.is_file() and "GeomSkin" in str(f) and SKIN_GUID in f.name.upper()]
    assert len(files) == 1, f"one compiled skin: {files}"
    return files[0].read_bytes()


def test_the_bone_addressing_packs_and_validates_on_synthetic_meshes():
    """The compiler's own cluster split on synthetic meshes: the span and distinct-bone boundaries, a mixed geometry with palettes that do not
    start at 0, a vertex shared by a base-offset and a palette cluster, the packed field, and the loader's validation of corrupt resources."""
    run = subprocess.run([str(compiler_exe("xgeom_skin")), "-SELFTEST"], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0 and "SELFTEST: OK" in run.stdout, run.stdout + run.stderr


def test_walking_needs_no_palette_and_compiles_the_same_bytes_twice(project):
    skin = "Descriptors\\" + folder("GeomSkin", SKIN_GUID) + ".desc"
    base, palette, entries = addressing(compile_one(project, "xgeom_skin", skin))
    assert base > 0 and palette == 0 and entries == 0, "every cluster of Walking.fbx fits the base offset: an empty BoneMap"
    first = compiled_skin(project)
    compile_one(project, "xgeom_skin", skin)
    assert compiled_skin(project) == first, "the same input gives the same binary"


LADY = REPO / "example.lionprj/Assets/LadyNJ/lady.fbx"

def test_a_952_bone_rig_compiles_with_palettes_deterministically(tmp_path):
    """lady.fbx: a shoulder vertex's bones lie 179 skeleton slots apart, more than the base offset reaches: its clusters use palettes."""
    if not LADY.exists():
        pytest.fail(f"the example project's model is missing: {LADY}")
    prj = tmp_path / "t.lionprj"
    (prj / "Assets/LadyNJ").mkdir(parents=True)
    shutil.copy(LADY, prj / "Assets/LadyNJ/lady.fbx")
    desc = prj / "Descriptors" / (folder("GeomSkin", SKIN_GUID) + ".desc")
    desc.mkdir(parents=True)
    (desc / "Descriptor.txt").write_text(HEADER + """[ xProperties : 4 ]
{ Name:s  Value:? }
  "GeomSkin/ImportAsset" ;wstring "Assets\\\\LadyNJ\\\\lady.fbx"
  "GeomSkin/bMergeAllMeshes" ;bool 1
  "GeomSkin/AllMeshesDetails/Name" ;string "Lady"
  "GeomSkin/ImportMaterials/bImport" ;bool 0
""")
    (prj / "Cache/Resources/Platforms").mkdir(parents=True)
    skin = "Descriptors\\" + folder("GeomSkin", SKIN_GUID) + ".desc"
    base, palette, entries = addressing(compile_one(prj, "xgeom_skin", skin))
    assert palette > 0 and entries > 0, "the wide clusters use palettes"
    first = compiled_skin(prj)
    compile_one(prj, "xgeom_skin", skin)
    assert compiled_skin(prj) == first, "the same input gives the same binary"
