"""A geometry with "Import materials and textures" on (GeomStatic/ImportMaterials/bImport, GeomSkin the same) makes one virtual Material
Instance per material of its model, with virtual Textures in its PBR slots (plugins/xmaterial_instance.plugin/source/Compiler/
xmaterial_instance_import_compiler.h). The static geom compiler is run here on a project of its own (a model of three materials written by
the test: one textured with a normal map, one cut out by an opacity map, one plain color whose emissive color makes it a light), and what
it wrote in Cache/Descriptors is read back. No editor: the editor half (override arrows, SetImportMaterials, DuplicateImportedMaterial) is
drawn by the geometry editors.
(The compiler is its own executable: build plugins/xgeom_static.plugin/build/xgeom_static_compiler.vs2022 first when it changed.)
"""
import os
import re
import struct
import subprocess
import zlib
from pathlib import Path

import pytest

from harness import compiler_exe

pytestmark = pytest.mark.no_editor

GEOM_GUID = "1234567890AB0005"         # its "stone" instance is 05DD7F9D9C42C09F: a guid with a leading zero (see test_folders_are_named_without_leading_zeros)
PBR       = "8D45F86DC5F2C003"          # xmaterial_instance::import::default_pbr_material_v
ALPHA     = "FF22104E737E58EB"          # default_pbr_alpha_test_material_v

HEADER = """[ DescriptorVersion ]
{ Major:d  Minor:d }
     1        0

< s32:d u32:g s16:C u16:H s8:c u8:h f32:f f64:F string:s wstring:S u64:G s64:D bool:c full_guid:GG enum:s >

"""

# What the material compiler leaves in its log for the PBR materials: the slots an instance has
TEMPLATE = """< s32:d u32:g s16:C u16:H s8:c u8:h f32:f f64:F string:s wstring:S u64:G s64:D bool:c full_guid:GG enum:s >

[ xProperties : 17 ]
{ Name:s  Value:? }
  "material_instance_descriptor/MaterialRef" ;full_guid #{guid} #8B3C028882EA813D
  "material_instance_descriptor/Textures[]" ;s64 0
  "material_instance_descriptor/TextureDefaults[]" ;s64 3
  "material_instance_descriptor/TextureDefaults[G:0]/Name" ;string "SamplerNormal"
  "material_instance_descriptor/TextureDefaults[G:0]/Index" ;s32 1
  "material_instance_descriptor/TextureDefaults[G:0]/GUID" ;u64 #6E
  "material_instance_descriptor/TextureDefaults[G:1]/Name" ;string "SamplerAlbedo"
  "material_instance_descriptor/TextureDefaults[G:1]/Index" ;s32 2
  "material_instance_descriptor/TextureDefaults[G:1]/GUID" ;u64 #78
  "material_instance_descriptor/TextureDefaults[G:2]/Name" ;string "SamplerORME"
  "material_instance_descriptor/TextureDefaults[G:2]/Index" ;s32 3
  "material_instance_descriptor/TextureDefaults[G:2]/GUID" ;u64 #82
  "material_instance_descriptor/FinalTextures[]" ;s64 4
  "material_instance_descriptor/FinalTextures[G:0]/TextureRef" ;full_guid #A8AC000D81D711F3 #6701D481518BD833
  "material_instance_descriptor/FinalTextures[G:1]/TextureRef" ;full_guid #189E50CFD884005F #6701D481518BD833
  "material_instance_descriptor/FinalTextures[G:2]/TextureRef" ;full_guid #6542000CC1D6FB6F #6701D481518BD833
  "material_instance_descriptor/FinalTextures[G:3]/TextureRef" ;full_guid #189EDF8BF1940033 #6701D481518BD833
"""

OBJ = """mtllib model.mtl
v 0 0 0
v 1 0 0
v 1 1 0
v 0 1 0
vt 0 0
vt 1 0
vt 1 1
vt 0 1
vn 0 0 1
usemtl stone
f 1/1/1 2/2/1 3/3/1
usemtl leaf
f 1/1/1 3/3/1 4/4/1
usemtl lamp
f 2/2/1 3/3/1 4/4/1
"""

MTL = """newmtl stone
Kd 0.5 0.5 0.5
map_Kd textures\\stone_diff.png
map_bump textures\\stone_ddn.png
newmtl leaf
Kd 1 1 1
map_Kd textures\\leaf_diff.png
map_d textures\\leaf_mask.png
newmtl lamp
Kd 0.8 0.8 0.8
Ke 17 12 4
Ns 10
"""


def png(path: Path, rgba: tuple[int, int, int, int], size: int = 4) -> None:
    """A solid RGBA PNG (stdlib only)."""
    raw = b"".join(b"\x00" + bytes(rgba) * size for _ in range(size))
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def guid_folder(root: Path, type_name: str, guid: str) -> Path:
    v = int(guid, 16)
    return root / type_name / f"{v & 0xFF:02X}" / f"{(v >> 8) & 0xFF:02X}" / f"{v:X}.desc"


@pytest.fixture
def project(tmp_path):
    prj = tmp_path / "t.lionprj"
    (prj / "Assets/model/textures").mkdir(parents=True)
    (prj / "Assets/model/model.obj").write_text(OBJ)
    (prj / "Assets/model/model.mtl").write_text(MTL)
    png(prj / "Assets/model/textures/stone_diff.png", (120, 110, 100, 255))
    png(prj / "Assets/model/textures/stone_ddn.png",  (128, 128, 255, 255))
    png(prj / "Assets/model/textures/leaf_diff.png",  (40, 160, 40, 255))
    png(prj / "Assets/model/textures/leaf_mask.png",  (255, 255, 255, 255))

    for guid in (PBR, ALPHA):
        v = int(guid, 16)
        log = prj / "Cache/Resources/Logs/Material" / f"{v & 0xFF:02X}" / f"{(v >> 8) & 0xFF:02X}" / f"{v:X}.log"
        log.mkdir(parents=True)
        (log / "MaterialInstance.txt").write_text(TEMPLATE.replace("{guid}", guid))

    desc = guid_folder(prj / "Descriptors", "GeomStatic", GEOM_GUID)
    desc.mkdir(parents=True)
    (desc / "Descriptor.txt").write_text(HEADER + """[ xProperties : 5 ]
{ Name:s  Value:? }
  "GeomStatic/ImportAsset" ;wstring "Assets\\\\model\\\\model.obj"
  "GeomStatic/bMergeAllMeshes" ;bool 1
  "GeomStatic/AllMeshesDetails/Name" ;string "Model"
  "GeomStatic/GI/Mode" ;enum "OFF"
  "GeomStatic/ImportMaterials/bImport" ;bool 1
""")
    (prj / "Cache/Resources/Platforms").mkdir(parents=True)
    return prj


def compile_geom(prj: Path) -> str:
    exe = compiler_exe("xgeom_static")
    if not exe.exists():
        pytest.fail(f"build the static geom compiler first: {exe}")
    v = int(GEOM_GUID, 16)
    run = subprocess.run([str(exe), "-PROJECT", str(prj), "-OPTIMIZATION", "O1", "-DEBUG", "D0"
                         , "-DESCRIPTOR", f"Descriptors\\GeomStatic\\{v & 0xFF:02X}\\{(v >> 8) & 0xFF:02X}\\{v:X}.desc"
                         , "-OUTPUT", str(prj / "Cache/Resources/Platforms")], capture_output=True, text=True, timeout=120)
    out = run.stdout + run.stderr
    assert "[COMPILATION_SUCCESS]" in out, out[-3000:]
    return out


def virtual(prj: Path, type_name: str) -> dict[str, tuple[str, str]]:
    """name -> (folder name, descriptor text) of every virtual resource of a type"""
    found = {}
    for info in (prj / "Cache/Descriptors" / type_name).rglob("Info.txt"):
        name = re.search(r'"Info/Name"\s+;string\s+"([^"]*)"', info.read_text())[1]
        found[name] = (info.parent.name.removesuffix(".desc"), (info.parent / "Descriptor.txt").read_text())
    return found


def texture_of(text: str, slot_index: int) -> str:
    return re.search(rf'"material_instance_descriptor/Textures\[G:{slot_index}\]"\s+;full_guid\s+#([0-9A-F]+)', text)[1]


def test_each_material_of_the_model_becomes_a_pbr_instance_with_its_textures(project):
    out = compile_geom(project)
    instances = virtual(project, "MaterialInstance")
    textures  = virtual(project, "Texture")
    assert set(instances) == {"stone", "leaf", "lamp"}, out[-2000:]

    # The instances are made from the PBR materials: the cut out one from the alpha test one
    assert f"#{PBR} " in instances["stone"][1] and f"#{PBR} " in instances["lamp"][1]
    assert f"#{ALPHA} " in instances["leaf"][1], "an opacity map makes the instance alpha tested"

    by_folder = {folder: (name, text) for name, (folder, text) in textures.items()}
    # Slots: 0 SamplerNormal, 1 SamplerAlbedo, 2 SamplerORME (the template's order)
    stone_normal = by_folder[texture_of(instances["stone"][1], 0)]
    assert "TANGENT_NORMAL" in stone_normal[1] and "stone_ddn.png" in stone_normal[1], "an OBJ bump map named like a normal map is the normal map"
    leaf_albedo = by_folder[texture_of(instances["leaf"][1], 1)]
    assert "MIX_SOURCE" in leaf_albedo[1] and "leaf_mask.png" in leaf_albedo[1] and "COLOR_AND_ALPHA" in leaf_albedo[1], "the opacity map goes in the albedo's alpha"

    lamp_albedo = by_folder[texture_of(instances["lamp"][1], 1)]
    assert "CUSTOM_CONSTANT" in lamp_albedo[1] and re.search(r'"Texture/SRGB"\s+;bool\s+0', lamp_albedo[1]), "a plain color is a linear constant texture"
    lamp_orme = by_folder[texture_of(instances["lamp"][1], 2)]
    assert re.search(r'Mixes\[G:3\]/Copy To"\s+;enum\s+"A"\s*\n\s*"Texture/Input/Mixes\[G:3\]/FileName"\s+;wstring\s+""\s*\n\s*"Texture/Input/Mixes\[G:3\]/Constant"\s+;f32\s+#3F800000', lamp_orme[1]), "an emissive color makes the material emit (ORME.a = 1)"

    # Shared: the flat-normal texture of the two materials without a normal map is one resource
    assert texture_of(instances["leaf"][1], 0) == texture_of(instances["lamp"][1], 0)


def test_folders_are_named_without_leading_zeros(project):
    """xresource_mgr loads by {:X}: a virtual resource whose folder had a leading zero could never be loaded."""
    compile_geom(project)
    assert (project / "Cache/Descriptors/MaterialInstance/9F/C0/5DD7F9D9C42C09F.desc").is_dir(), "the stone instance, named by {:X}"
    for folder in (project / "Cache/Descriptors").rglob("*.desc"):
        guid = folder.name[:-len(".desc")]
        assert guid == f"{int(guid, 16):X}", folder


def test_recompiling_rewrites_nothing_that_did_not_change(project):
    """The virtual descriptors keep their time: a recompile of the geometry does not recompile its textures."""
    compile_geom(project)
    before = {p: p.stat().st_mtime_ns for p in (project / "Cache/Descriptors").rglob("*.txt")}
    compile_geom(project)
    after = {p: p.stat().st_mtime_ns for p in (project / "Cache/Descriptors").rglob("*.txt")}
    assert before == after


def test_a_missing_texture_warns_and_the_material_still_gets_an_instance(project):
    (project / "Assets/model/textures/stone_diff.png").unlink()
    out = compile_geom(project)
    assert "stone_diff.png not found" in out
    assert "stone" in virtual(project, "MaterialInstance")


def test_with_the_import_off_nothing_is_made(project):
    desc = guid_folder(project / "Descriptors", "GeomStatic", GEOM_GUID) / "Descriptor.txt"
    desc.write_text(desc.read_text().replace('"GeomStatic/ImportMaterials/bImport" ;bool 1', '"GeomStatic/ImportMaterials/bImport" ;bool 0'))
    compile_geom(project)
    assert not (project / "Cache/Descriptors").exists() or not list((project / "Cache/Descriptors").rglob("*.desc"))
