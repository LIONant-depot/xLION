"""A skin with "Import the skeleton and the animations" on (GeomSkin/ImportAnimation) makes a virtual Skeleton and a virtual Anim Package of
its model, like the imported materials: the skin compiler binds its bones with the bone manifest it builds itself (xskeleton_merge.h, the
Skeleton compiler's own code), since the skeleton compiles after it. Here the three compilers run in the pipeline's order on a project of
their own (the example project's Walking.fbx): the skin binds without a compiled skeleton, the generated skeleton and package compile on
it, and a second compile makes the same resources. No editor: the
SkeletonRef's override arrow and the preview's default animation are drawn by the skin editor.
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
    compile_one(project, "xgeom_skin", "Descriptors\\" + folder("GeomSkin", SKIN_GUID) + ".desc")

    skeletons, packages = virtual(project, "Skeleton"), virtual(project, "AnimPackage")
    assert len(skeletons) == 1 and len(packages) == 1, "one generated skeleton and one generated anim package"
    skeleton_guid = skeletons[0].name.removesuffix(".desc")
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

    skeleton.write_text(skeleton.read_text().replace('"Skeleton/PreTransform/Scale/X"              ;f32     #3F800000', '"Skeleton/PreTransform/Scale/X"              ;f32     #40000000'))
    package.write_text(re.sub(r'("AnimPackage/SkeletonRef"\s+;full_guid\s+)#[0-9A-F]+', r"\1#1234", package.read_text()))
    skeleton_stamp = skeleton.stat().st_mtime_ns

    compile_one(project, "xgeom_skin", skin)
    text = skeleton.read_text()
    assert re.search(r'"Skeleton/PreTransform/Scale/X"\s+;f32\s+#40000000', text), "the pre-transform is the user's"
    assert skeleton.stat().st_mtime_ns == skeleton_stamp, "the skeleton was not written: nothing of it changed"
    assert re.search(rf'"AnimPackage/SkeletonRef"\s+;full_guid\s+#{skeleton_guid} ', package.read_text()), "the skeleton of the package is the skin's"
