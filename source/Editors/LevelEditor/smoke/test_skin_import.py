"""The skin editor with ImportSkeletonAndAnimation on (the default of a new skin): after a compile its SkeletonRef and AnimationRef are the generated Skeleton and Anim
Package (read-only rows: set by the editor, not by the user), the preview plays the package, and turning the flag off gives the skeleton back to the user and
empties the AnimationRef. The skin is made by the test from the example project's Walking.fbx; the project guard removes what it leaves.
"""
import re
import secrets
import time

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
