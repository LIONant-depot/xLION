"""The skin editor with ImportSkeletonAndAnimation on (the default of a new skin): after a compile its SkeletonRef and AnimationRef are the generated Skeleton and Anim
Package (read-only rows: set by the editor, not by the user), the preview plays the package, and turning the flag off gives the skeleton back to the user and
empties the AnimationRef. The skin is made by the test from the example project's Walking.fbx; the project guard removes what it leaves.
"""
import re
import secrets
import time
from pathlib import Path

import pytest

from harness import REPO, quote

PROJECT     = REPO / "example.lionprj"
SKIN_TYPE   = "0615D479BCA3267B"
FOLDER_TYPE = "C4D90C5F0CC43021"


def generated(type_name: str, owner: str) -> list[str]:
    """The hex guids of the virtual resources of a type whose Info links the owner as the parent"""
    found = []
    for info in (PROJECT / "Descriptors" / type_name).rglob("Info.txt"):
        if f"#{int(owner[:16], 16):X} " in info.read_text(errors="replace"):
            found.append(info.parent.name.removesuffix(".desc"))
    return found


def wait_idle(editor, timeout=180):
    deadline = time.time() + timeout
    time.sleep(1)
    while time.time() < deadline and "Compiling=0 Waiting=0" not in editor.cmd("CompileStatus"):
        time.sleep(0.5)


def ref(editor, asset: str, name: str) -> str:
    text = editor.cmd(f"ResourceEditorCommand -Asset {asset} -Cmd ListProperties")
    m = re.search(rf"GeomSkin/{name} = ([0-9A-Fa-f]+)", text)
    return m[1].upper() if m else ""


@pytest.fixture
def skin(editor):
    lib = editor.libraries()[0][0]
    asset = "%016X" % (secrets.randbits(63) | 1) + SKIN_TYPE
    editor.ok(f"CreateAsset -Library {lib} -Type {SKIN_TYPE} -Asset {asset} -Parent {lib}{FOLDER_TYPE} -Name SmokeSkinImport", allow_disk=True)
    editor.ok(f"OpenResourceEditor -Asset {asset} -Library {lib}", timeout=30)
    for path, value in (("GeomSkin/ImportAsset", r"Assets\WalkingSkin\Walking.fbx"), ("GeomSkin/AllMeshesDetails/Name", "Walking"), ("GeomSkin/ImportMaterials/bImport", "false")):
        editor.ok(f"ResourceEditorCommand -Asset {asset} -Cmd {quote(f'SetProperty -Path {quote(path)} -Value {quote(value)}')}")
    try:
        yield lib, asset
    finally:
        editor.cmd(f"CloseResourceEditor -Asset {asset}")


def test_the_refs_are_the_generated_skeleton_and_package(editor, skin):
    lib, asset = skin
    reply = editor.cmd(f"ResourceEditorCommand -Asset {asset} -Cmd Compile", allow_disk=True)
    assert "compile queued" in reply, reply
    wait_idle(editor)

    skeletons, packages = generated("Skeleton", asset), generated("AnimPackage", asset)
    assert len(skeletons) == 1 and len(packages) == 1, "the compile made a skeleton and a package"
    deadline = time.time() + 20
    while time.time() < deadline and not (ref(editor, asset, "AnimationRef").strip("0") and ref(editor, asset, "SkeletonRef").strip("0")):
        time.sleep(0.5)                                              # the editor follows the compile on its next frame
    assert skeletons[0] in ref(editor, asset, "SkeletonRef"), "the SkeletonRef is the generated skeleton"
    assert packages[0] in ref(editor, asset, "AnimationRef"), "the AnimationRef is the generated package"
    assert editor.alive()


def test_turning_the_import_off_gives_the_skeleton_back_to_the_user(editor, skin):
    lib, asset = skin
    editor.cmd(f"ResourceEditorCommand -Asset {asset} -Cmd Compile", allow_disk=True)
    wait_idle(editor)
    deadline = time.time() + 20
    while time.time() < deadline and not ref(editor, asset, "AnimationRef").strip("0"):
        time.sleep(0.5)
    assert ref(editor, asset, "AnimationRef").strip("0")

    editor.ok(f"ResourceEditorCommand -Asset {asset} -Cmd {quote('SetProperty -Path ' + quote('GeomSkin/ImportSkeletonAndAnimation') + ' -Value false')}")
    deadline = time.time() + 20
    while time.time() < deadline and ref(editor, asset, "AnimationRef").strip("0"):
        time.sleep(0.5)
    assert not ref(editor, asset, "AnimationRef").strip("0"), "the AnimationRef is empty again"
    assert not ref(editor, asset, "SkeletonRef").strip("0"), "and the generated skeleton is let go: the user chooses one"


def log_of(type_name: str, guid: str) -> Path:
    v = int(guid[:16], 16)
    return PROJECT / "Cache/Resources/Logs" / type_name / f"{v & 0xFF:02X}" / f"{(v >> 8) & 0xFF:02X}" / f"{v:X}.log"


def skin_size(asset: str) -> list[float]:
    return [float(x) for x in re.search(r"Size (\S+) (\S+) (\S+)", (log_of("GeomSkin", asset) / "Log.txt").read_text(errors="replace")).groups()]


def test_scaling_the_skeleton_recompiles_the_skin_and_its_animations(editor, skin):
    """The skeleton is the master: the user scales it (its PreTransform, saved to its descriptor) and the editor compiles the skeleton, the skin (its mesh in
    the skeleton's space) and the animations (their root keys) again, with nothing else done by hand."""
    lib, asset = skin
    editor.cmd(f"ResourceEditorCommand -Asset {asset} -Cmd Compile", allow_disk=True)
    wait_idle(editor)
    skeletons, packages = generated("Skeleton", asset), generated("AnimPackage", asset)
    assert len(skeletons) == 1 and len(packages) == 1
    before = skin_size(asset)
    stamps = {name: (log_of(kind, guid) / "Log.txt").stat().st_mtime_ns for name, kind, guid in (("skin", "GeomSkin", asset), ("skeleton", "Skeleton", skeletons[0]), ("package", "AnimPackage", packages[0]))}

    v = int(skeletons[0], 16)
    descriptor = PROJECT / "Descriptors/Skeleton" / f"{v & 0xFF:02X}" / f"{(v >> 8) & 0xFF:02X}" / f"{v:X}.desc" / "Descriptor.txt"
    text, n = re.subn(r'("Skeleton/PreTransform/Scale/[XYZ]"\s+;f32\s+)#3F800000', r"\1#3C23D70A", descriptor.read_text())     # 0.01
    assert n == 3, "a new skeleton has no pre-transform"
    time.sleep(1.1)                                                     # a time the file system tells apart from the compile's
    descriptor.write_text(text)

    deadline = time.time() + 600
    while time.time() < deadline:
        now = {name: (log_of(kind, guid) / "Log.txt").stat().st_mtime_ns for name, kind, guid in (("skin", "GeomSkin", asset), ("skeleton", "Skeleton", skeletons[0]), ("package", "AnimPackage", packages[0]))}
        if all(now[k] > stamps[k] for k in now) and "Compiling=0 Waiting=0" in editor.cmd("CompileStatus"):
            break
        time.sleep(0.5)
    assert all(now[k] > stamps[k] for k in now), f"compiled again after the skeleton changed: { {k: now[k] > stamps[k] for k in now} }"
    manifest = (log_of("Skeleton", skeletons[0]) / "AnimPackage.txt").read_text(errors="replace")
    assert re.search(r'"bone_manifest/PreTransformScale/X"\s+;f32\s+#3C23D70A', manifest), "the skeleton was compiled with the new scale"
    after = skin_size(asset)
    assert all(abs(a - b * 0.01) <= b * 0.0002 + 1e-4 for a, b in zip(after, before)), f"the mesh follows the skeleton: {before} -> {after}"
    assert editor.alive()
