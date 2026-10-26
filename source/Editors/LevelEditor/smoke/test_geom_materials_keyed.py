"""A GeomStatic descriptor's materials are addressed by their name ("MaterialDetailsList[G:<key>]/...", key = FNV-1a 64 of the name), each with its own
Instance; the MaterialInstance list the editor shows (by place) is not saved any more. A file of the old form (by place, the instances beside them) reads
the same; source/Tools/Scripts/convert_keyed_geom_materials.py rewrites one. The descriptor the test saves is put back when the run ends (project_guard)."""
import re
import sys

from harness import REPO, quote

sys.path.insert(0, str(REPO / "source" / "Tools" / "Scripts"))
from convert_keyed_geom_materials import convert, name_key      # noqa: E402

CUBE = "5E1CE0A110000009"                   # SliceCube: one material
ASSET = CUBE + "E5359948C52D26D1"            # instance + type (GeomStatic)
DESC = REPO / "example.lionprj" / "Descriptors" / "GeomStatic" / "09" / "00" / f"{CUBE}.desc" / "Descriptor.txt"

OLD = b"""[ xProperties : 6 ]
{ Name:s  Value:? }
//------  -------
  "GeomStatic/MaterialDetailsList[]"            ;s64        1
  "GeomStatic/MaterialDetailsList[G:0]/Name"    ;string     "Red"
  "GeomStatic/MaterialDetailsList[G:0]/RefCount" ;s32       1
  "GeomStatic/MaterialInstance[]"               ;s64        1
  "GeomStatic/MaterialInstance[G:0]"            ;full_guid  #5E1CE0A110000003 #B673C5DA4A4A70AD
  "GeomStatic/bMergeAllMeshes"                  ;bool       1
"""


def test_the_converter_writes_a_material_by_its_name_with_its_instance():
    new = convert(OLD)
    key = name_key(b"Red")
    assert new is not None and b"MaterialInstance" not in new
    assert f'"GeomStatic/MaterialDetailsList[G:{key}]/Name"'.encode() in new
    assert re.search(rb'"GeomStatic/MaterialDetailsList\[G:%d\]/Instance"\s+;full_guid\s+#5E1CE0A110000003 #B673C5DA4A4A70AD' % key, new)
    assert b"[ xProperties : 5 ]" in new, "the block's row count follows (the list and its count row out, one Instance row in)"
    assert convert(new) is None, "a converted file is left alone"


def test_the_editor_reads_and_saves_the_materials_by_name(editor):
    text = DESC.read_text()
    names = re.findall(r'"GeomStatic/MaterialDetailsList\[G:(\d+)\]/Name"\s+;string\s+"([^"]*)"', text)
    assert names and "MaterialInstance[" not in text, "the project's descriptor is of the new form (converted)"
    for key, name in names:
        assert int(key) == name_key(name.encode()), "the key is the name's"
    instance = re.search(rf'"GeomStatic/MaterialDetailsList\[G:{names[0][0]}\]/Instance"\s+;full_guid\s+#(\w+)', text)[1]

    lib = editor.libraries()[0][0]
    editor.ok(f"OpenResourceEditor -Asset {ASSET} -Library {lib}", timeout=30)
    listed = editor.cmd(f"ResourceEditorCommand -Asset {ASSET} -Cmd {quote('ListProperties -Filter MaterialInstance')}")
    assert re.search(rf"MaterialInstance\[G:0\]\s*=\s*{instance}", listed, re.I), f"the editor's list (by place) holds the material's instance: {listed}"

    editor.cmd(f"ResourceEditorCommand -Asset {ASSET} -Cmd Save", allow_disk=True)
    saved = DESC.read_text()
    assert "MaterialInstance[" not in saved and f'MaterialDetailsList[G:{names[0][0]}]/Instance' in saved, "saved by name, each with its instance"
