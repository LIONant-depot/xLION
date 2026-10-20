"""A geometry with "Import materials and textures" on (GeomStatic/ImportMaterials/bImport, GeomSkin the same) makes one virtual Material
Instance per material of its model, with virtual Textures in its PBR slots (plugins/xmaterial_instance.plugin/source/Compiler/
xmaterial_instance_import_compiler.h). The static geom compiler is run here on a project of its own (a model of three materials written by
the test: one textured with a normal map, one cut out by an opacity map, one plain color whose emissive color makes it a light), and what
it wrote in Descriptors (the virtual resources are descriptors like the others) is read back. No editor: the editor half (override arrows, SetImportMaterials, DuplicateImportedMaterial) is
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
    for info in (prj / "Descriptors" / type_name).rglob("Info.txt"):
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
    assert re.search(r'"Texture/Usage"\s+;enum\s+"INTENSITY"', lamp_orme[1]), "the ORME is data (an intensity texture), not a color with alpha"
    assert re.search(r'Mixes\[G:3\]/Copy To"\s+;enum\s+"A"\s*\n\s*"Texture/Input/Mixes\[G:3\]/FileName"\s+;wstring\s+""\s*\n\s*"Texture/Input/Mixes\[G:3\]/Constant"\s+;f32\s+#3F800000', lamp_orme[1]), "an emissive color makes the material emit (ORME.a = 1)"

    # Shared: the flat-normal texture of the two materials without a normal map is one resource
    assert texture_of(instances["leaf"][1], 0) == texture_of(instances["lamp"][1], 0)


def test_folders_are_named_without_leading_zeros(project):
    """xresource_mgr loads by {:X}: a virtual resource whose folder had a leading zero could never be loaded."""
    compile_geom(project)
    assert (project / "Descriptors/MaterialInstance/9F/C0/5DD7F9D9C42C09F.desc").is_dir(), "the stone instance, named by {:X}"
    for folder in (project / "Descriptors").rglob("*.desc"):
        guid = folder.name[:-len(".desc")]
        assert guid == f"{int(guid, 16):X}", folder


def test_recompiling_rewrites_nothing_that_did_not_change(project):
    """The virtual descriptors keep their time: a recompile of the geometry does not recompile its textures."""
    compile_geom(project)
    before = {p: p.stat().st_mtime_ns for p in (project / "Descriptors").rglob("*.txt")}
    compile_geom(project)
    after = {p: p.stat().st_mtime_ns for p in (project / "Descriptors").rglob("*.txt")}
    assert before == after


def test_a_missing_texture_warns_and_the_material_still_gets_an_instance(project):
    (project / "Assets/model/textures/stone_diff.png").unlink()
    out = compile_geom(project)
    assert "stone_diff.png not found" in out
    assert "stone" in virtual(project, "MaterialInstance")


def test_a_texture_next_to_the_model_under_a_copys_name_is_found(project):
    """The model names stone_diff.png, the folder holds "stone_diff - Copy.png" (a file manager's copy): the last search finds it, it is not magenta."""
    textures = project / "Assets/model/textures"
    (textures / "stone_diff.png").rename(textures / "stone_diff - Copy.png")
    out = compile_geom(project)
    assert "stone_diff.png not found" not in out, out[-3000:]
    assert "stone_diff.png found as" in out and "stone_diff - Copy.png" in out
    assert "Missing texture" not in virtual(project, "Texture"), "no placeholder"


def test_a_texture_converted_to_another_image_format_is_found(project):
    """The model names stone_diff.png, the folder holds stone_diff.tga (the same name in another format): found, not magenta."""
    textures = project / "Assets/model/textures"
    (textures / "stone_diff.png").rename(textures / "stone_diff.tga")   # stb reads by content, the extension is only a name
    out = compile_geom(project)
    assert "stone_diff.png not found" not in out, out[-3000:]
    assert "stone_diff.png found as" in out and "stone_diff.tga" in out
    assert "Missing texture" not in virtual(project, "Texture"), "no placeholder"


def test_a_glossiness_map_is_the_roughness_upside_down(project):
    """map_Ns is FBX's glossiness: the ORME takes it into G inverted (roughness = 1 - glossiness) instead of a constant."""
    obj = project / "Assets/model"
    png(obj / "textures/stone_gloss.png", (200, 200, 200, 255))
    mtl = obj / "model.mtl"
    mtl.write_text(mtl.read_text().replace("map_bump textures\\stone_ddn.png", "map_bump textures\\stone_ddn.png\nmap_Ns textures\\stone_gloss.png"))
    compile_geom(project)
    orme = virtual(project, "Texture")["stone_gloss (ORME)"][1]
    assert re.search(r'"Texture/Usage"\s+;enum\s+"INTENSITY"', orme), "the ORME is data (an intensity texture), not a color with alpha"
    assert re.search(r'Mixes\[G:1\]/Invert"\s+;bool\s+1', orme) and "stone_gloss.png" in orme, orme


def test_a_roughness_map_in_the_shininess_slot_is_used_as_it_is(project):
    """map_Ns names stone_rough.png: its name says roughness (xLION is roughness based), so it goes into G as it is, not upside down."""
    obj = project / "Assets/model"
    png(obj / "textures/stone_rough.png", (200, 200, 200, 255))
    mtl = obj / "model.mtl"
    mtl.write_text(mtl.read_text().replace("map_bump textures\\stone_ddn.png", "map_bump textures\\stone_ddn.png\nmap_Ns textures\\stone_rough.png"))
    compile_geom(project)
    orme = virtual(project, "Texture")["stone_rough (ORME)"][1]
    assert re.search(r'Mixes\[G:1\]/Invert"\s+;bool\s+0', orme) and "stone_rough.png" in orme, orme


def test_a_material_with_no_map_in_the_model_finds_its_maps_by_its_own_name(project):
    """The model gives the material lamp no map at all (an FBX that lost its links), but lamp_Albedo.png, lamp_Rough.png and lamp_Emissive.png sit in the textures
    folder: they are its color, its roughness (as it is, xLION is roughness based) and the mask of its emission."""
    textures = project / "Assets/model/textures"
    png(textures / "lamp_Albedo.png",   (200, 180, 90, 255))
    png(textures / "lamp_Rough.png",    (90, 90, 90, 255))
    png(textures / "lamp_Emissive.png", (255, 255, 255, 255))
    out = compile_geom(project)
    assert "lamp_Albedo.png (named after the material or the model) is taken" in out, out[-3000:]
    orme = virtual(project, "Texture")["lamp_Rough (ORME)"][1]
    assert re.search(r'Mixes\[G:1\]/Invert"\s+;bool\s+0', orme) and "lamp_Rough.png" in orme, orme
    assert "lamp_Emissive.png" in orme, "the emissive map is the mask of the emission (ORME.a)"


def test_a_material_with_no_map_finds_the_maps_named_after_the_model(project):
    """The maps are named after the model (model.obj: model_Cor.jpeg, modelRough.jpeg: Portuguese 'cor' is the color, no separator), not after its material lamp."""
    textures = project / "Assets/model/textures"
    png(textures / "model_Cor.jpeg",    (200, 180, 90, 255))
    png(textures / "modelRough.jpeg",   (90, 90, 90, 255))
    out = compile_geom(project)
    assert "model_Cor.jpeg (named after the material or the model) is taken" in out, out[-3000:]
    orme = virtual(project, "Texture")["modelRough (ORME)"][1]
    assert re.search(r'Mixes\[G:1\]/Invert"\s+;bool\s+0', orme) and "modelRough.jpeg" in orme, orme


def test_the_instances_of_a_particle_system_have_a_material_of_their_own_with_the_unclaimed_maps(project):
    """A node named x|Dupli|n (Blender's instanced hair cards) shares the model's material lamp (it names no map), but is a slot of its own, "lamp|Dupli": it takes
    the set of maps no material took (feather_alpha.png and feather_normal.png), a cut-out of the material's color."""
    obj = project / "Assets/model/model.obj"
    obj.write_text(obj.read_text() + "o card|Dupli|0\nusemtl lamp\nf 1/1/1 2/2/1 3/3/1\n")
    textures = project / "Assets/model/textures"
    png(textures / "feather_alpha.png",  (255, 255, 255, 255))
    png(textures / "feather_normal.png", (128, 128, 255, 255))
    out = compile_geom(project)
    assert "lamp|Dupli: the opacity map is not named by the model, " in out and "feather_alpha.png (no other material has it) is taken" in out, out[-3000:]
    assert "lamp|Dupli" in virtual(project, "MaterialInstance"), "a slot of its own"
    assert "lamp" in virtual(project, "MaterialInstance"), "and the model's own"
    cut_out = virtual(project, "Texture")["feather_alpha (color, cut out)"][1]
    assert re.search(r'"Texture/Usage"\s+;enum\s+"COLOR_AND_ALPHA"', cut_out) and "feather_alpha.png" in cut_out, cut_out
    assert "feather_normal (normal)" in virtual(project, "Texture")


def test_an_unclaimed_alpha_map_with_an_alpha_channel_is_the_color_map_with_its_cut_out(project):
    """feather_alpha.png is an RGBA image (black feathers, their shape in the alpha channel), not a mask in the red channel: it is the color of the instanced cards."""
    obj = project / "Assets/model/model.obj"
    obj.write_text(obj.read_text() + "o card|Dupli|0\nusemtl lamp\nf 1/1/1 2/2/1 3/3/1\n")
    png(project / "Assets/model/textures/feather_alpha.png", (10, 10, 10, 0))
    out = compile_geom(project)
    assert "feather_alpha.png has its own alpha channel: it is the color map, with its cut-out" in out, out[-3000:]
    cut_out = virtual(project, "Texture")["feather_alpha (color and alpha)"][1]
    assert re.search(r'"Texture/Usage"\s+;enum\s+"COLOR_AND_ALPHA"', cut_out) and "feather_alpha.png" in cut_out, cut_out


def test_a_map_the_model_does_not_name_is_found_next_to_its_color_map_by_name(project):
    """stone_diff.png is the color map, stone_glossiness.png sits beside it and the model never names it: it is the roughness, upside down."""
    png(project / "Assets/model/textures/stone_glossiness.png", (200, 200, 200, 255))
    out = compile_geom(project)
    assert "stone_glossiness.png" in out and "is not named by the model" in out, out[-3000:]
    orme = virtual(project, "Texture")["stone_glossiness (ORME)"][1]
    assert re.search(r'Mixes\[G:1\]/Invert"\s+;bool\s+1', orme), orme


def test_a_slot_with_only_constants_takes_the_map_once_there_is_one(project):
    """The first compile has no roughness map: the ORME is constants. The map shows up next to the color map: the slot takes the new ORME (a slot with files stays, see the tests above)."""
    compile_geom(project)
    before = texture_of(virtual(project, "MaterialInstance")["stone"][1], 2)

    png(project / "Assets/model/textures/stone_glossiness.png", (200, 200, 200, 255))
    out = compile_geom(project)
    textures = {name: folder for name, (folder, _) in virtual(project, "Texture").items()}
    after = texture_of(virtual(project, "MaterialInstance")["stone"][1], 2)
    assert after == textures["stone_glossiness (ORME)"] != before, out[-3000:]
    assert "its constant SamplerORME is found" in out


def test_a_slot_whose_texture_is_gone_takes_the_new_one(project):
    """The texture of a slot was deleted (removed as unused): the slot is a missing one, it takes what the import makes now."""
    import shutil
    compile_geom(project)
    before = texture_of(virtual(project, "MaterialInstance")["stone"][1], 2)
    shutil.rmtree(guid_folder(project / "Descriptors", "Texture", before))

    png(project / "Assets/model/textures/stone_glossiness.png", (200, 200, 200, 255))
    compile_geom(project)
    textures = {name: folder for name, (folder, _) in virtual(project, "Texture").items()}
    assert texture_of(virtual(project, "MaterialInstance")["stone"][1], 2) == textures["stone_glossiness (ORME)"]


def test_with_the_import_off_nothing_is_made(project):
    desc = guid_folder(project / "Descriptors", "GeomStatic", GEOM_GUID) / "Descriptor.txt"
    desc.write_text(desc.read_text().replace('"GeomStatic/ImportMaterials/bImport" ;bool 1', '"GeomStatic/ImportMaterials/bImport" ;bool 0'))
    compile_geom(project)
    for type_name in ("MaterialInstance", "Texture"):
        assert not (project / "Descriptors" / type_name).exists() or not list((project / "Descriptors" / type_name).rglob("*.desc")), type_name


# ---------------------------------------------------------------------------------------------------------------------------------------------
# The virtual resources are the user's to edit: a compile updates only what the generator owns (xresource_pipeline_virtual.h)

def descriptor_of(prj: Path, type_name: str, folder: str) -> Path:
    return guid_folder(prj / "Descriptors", type_name, folder) / "Descriptor.txt"


def use_another_diffuse_map(prj: Path) -> None:
    """The model's color map of "stone" is another file now"""
    png(prj / "Assets/model/textures/stone_diff2.png", (200, 90, 90, 255))
    mtl = prj / "Assets/model/model.mtl"
    mtl.write_text(mtl.read_text().replace("stone_diff.png", "stone_diff2.png"))


def test_the_edits_of_a_generated_texture_survive_a_recompile(project):
    compile_geom(project)
    folder, text = virtual(project, "Texture")["stone_diff (color)"]
    path = descriptor_of(project, "Texture", folder)
    path.write_text(text.replace('"RGB_BC1"', '"RGBA_BC7"').replace("stone_diff.png", "stone_ddn.png"))      # its compression and its source file
    info = path.with_name("Info.txt")
    info.write_text(info.read_text().replace("stone_diff (color)", "My stone color"))
    compile_geom(project)
    assert '"RGBA_BC7"' in path.read_text() and "stone_ddn.png" in path.read_text(), "the compression and the source file are the user's (a texture has its guid from its input: the same guid never needs another)"
    stamp = path.stat().st_mtime_ns                                   # (the first compile wrote the text as the serializer does: an editor's save would)

    compile_geom(project)
    assert path.stat().st_mtime_ns == stamp, "and nothing is written any more: the texture is not compiled again"
    assert "My stone color" in info.read_text(), "the name too"


def test_a_slot_that_is_set_stays_when_the_model_names_another_texture(project):
    """An instance that exists is the user's: the import never updates its slots (Reapply in the editor is explicit)."""
    compile_geom(project)
    before = virtual(project, "MaterialInstance")["stone"][1]
    old = texture_of(before, 1)

    use_another_diffuse_map(project)
    compile_geom(project)
    after = virtual(project, "MaterialInstance")["stone"][1]
    assert texture_of(after, 1) == old, "the albedo stays the texture it was set to"
    assert after == before, "and nothing else of the instance changes"
    textures = {name: folder for name, (folder, _) in virtual(project, "Texture").items()}
    assert textures["stone_diff (color)"] == old, "the texture it holds stays on disk"


def test_a_missing_texture_is_magenta_until_it_is_found(project):
    """The one exception: a slot that still holds the magenta placeholder of a missing texture takes the texture once it is found."""
    (project / "Assets/model/textures/stone_diff.png").unlink()
    compile_geom(project)
    placeholder, text = virtual(project, "Texture")["Missing texture"]
    assert texture_of(virtual(project, "MaterialInstance")["stone"][1], 1) == placeholder, "the albedo is the placeholder"
    assert "CUSTOM_CONSTANT" in text and re.search(r'"Texture/SRGB"\s+;bool\s+0', text), "a constant (magenta) texture"

    png(project / "Assets/model/textures/stone_diff.png", (120, 110, 100, 255))
    compile_geom(project)
    textures = {name: folder for name, (folder, _) in virtual(project, "Texture").items()}
    assert texture_of(virtual(project, "MaterialInstance")["stone"][1], 1) == textures["stone_diff (color)"], "found: the slot takes it"


def test_a_slot_the_user_pointed_at_another_texture_is_kept(project):
    compile_geom(project)
    instances = virtual(project, "MaterialInstance")
    mine = "ABCDEF0123456789"                                         # a texture the geometry did not make (it exists: a texture that is gone is a missing one)
    guid_folder(project / "Descriptors", "Texture", mine).mkdir(parents=True)
    (guid_folder(project / "Descriptors", "Texture", mine) / "Descriptor.txt").write_text(HEADER)
    folder, text = instances["stone"]
    generated = texture_of(text, 1)
    path = descriptor_of(project, "MaterialInstance", folder)
    path.write_text(text.replace(f"#{generated} ", f"#{mine} ", 1))

    use_another_diffuse_map(project)                                  # the generator has something else to say about that slot
    compile_geom(project)
    after = virtual(project, "MaterialInstance")["stone"][1]
    assert texture_of(after, 1) == mine, "the user's choice stays"
    assert f"#{PBR} " in after, "the base material is the generator's"


def test_the_geometry_lists_what_it_made_and_without_a_list_it_is_written_again(project):
    compile_geom(project)
    lists = list((project / "Descriptors/GeomStatic").rglob("Virtual.txt"))
    assert len(lists) == 1, "one list, in the descriptor folder of the geometry"
    made = set(re.findall(r"full_guid\s+#([0-9A-F]+) ", lists[0].read_text()))
    every = {folder for type_name in ("MaterialInstance", "Texture") for folder, _ in virtual(project, type_name).values()}
    assert made == every, "every virtual resource of the geometry is on it"

    lists[0].unlink()                                                  # a project from before the lists
    before = virtual(project, "MaterialInstance")["stone"][1]
    compile_geom(project)
    assert lists[0].exists(), "the list is written again"
    assert set(re.findall(r"full_guid\s+#([0-9A-F]+) ", lists[0].read_text())) == made, "with the same resources (the Info links tell what the geometry made)"
    assert virtual(project, "MaterialInstance")["stone"][1] == before, "and the instance is not touched"


def test_a_generated_descriptor_that_cannot_be_read_is_left_alone_with_a_warning(project):
    """The user's file is never replaced by a fresh one: a half-edited descriptor (a merge conflict, a broken save) stays as it is until it is fixed."""
    compile_geom(project)
    folder, _ = virtual(project, "Texture")["stone_diff (color)"]
    path = descriptor_of(project, "Texture", folder)
    path.write_text("<<<<<<< merge conflict\n")
    out = compile_geom(project)
    assert path.read_text() == "<<<<<<< merge conflict\n", "it is left as it is"
    assert "could not be read: it is left as it is" in out


def compression_of(text: str) -> str:
    return re.search(r'"Texture/Compression"\s+;enum\s+"([A-Z0-9_]+)"', text)[1]


def test_the_import_settings_choose_the_compression_of_the_textures_made_from_now_on(project):
    compile_geom(project)
    textures = virtual(project, "Texture")
    assert compression_of(textures["stone_diff (color)"][1]) == "RGB_BC1", "a color map: BC1 by default"
    assert compression_of(textures["stone_ddn (normal)"][1]) == "RG_BC5", "a normal map: BC5"
    assert compression_of(textures["leaf_diff (color, cut out)"][1]) == "RGBA_BC7", "a color map that cuts out: BC7"

    desc = guid_folder(project / "Descriptors", "GeomStatic", GEOM_GUID) / "Descriptor.txt"
    desc.write_text(desc.read_text().replace("xProperties : 5", "xProperties : 7").replace('"GeomStatic/ImportMaterials/bImport" ;bool 1'
        , '"GeomStatic/ImportMaterials/bImport" ;bool 1\n  "GeomStatic/ImportMaterials/AlbedoCompression" ;enum "RGB_BC7"\n  "GeomStatic/ImportMaterials/NormalCompression" ;enum "RGBA_BC7"'))
    compile_geom(project)
    textures = virtual(project, "Texture")
    assert compression_of(textures["stone_diff (color)"][1]) == "RGB_BC1", "a texture that exists is the user's: the setting is not applied to it"

    stone = guid_folder(project / "Descriptors", "Texture", textures["stone_diff (color)"][0])
    normal = guid_folder(project / "Descriptors", "Texture", textures["stone_ddn (normal)"][0])
    import shutil
    shutil.rmtree(stone); shutil.rmtree(normal)
    compile_geom(project)
    textures = virtual(project, "Texture")
    assert compression_of(textures["stone_diff (color)"][1]) == "RGBA_BC7", "made again, it takes the setting"
    assert compression_of(textures["stone_ddn (normal)"][1]) == "RGBA_BC7"


def flip_of(text: str) -> int:
    found = re.search(r'"Texture/Normal Flip Y"\s+;bool\s+(\d)', text)
    return int(found[1]) if found else 0


def test_flip_y_for_normals_is_on_the_normal_maps_made_from_now_on_and_only_on_them(project):
    compile_geom(project)
    textures = virtual(project, "Texture")
    assert flip_of(textures["stone_ddn (normal)"][1]) == 0, "a model's normal maps are not flipped by default"

    desc = guid_folder(project / "Descriptors", "GeomStatic", GEOM_GUID) / "Descriptor.txt"
    desc.write_text(desc.read_text().replace("xProperties : 5", "xProperties : 6").replace('"GeomStatic/ImportMaterials/bImport" ;bool 1'
        , '"GeomStatic/ImportMaterials/bImport" ;bool 1\n  "GeomStatic/ImportMaterials/Flip Y for normals" ;bool 1'))
    compile_geom(project)
    textures = virtual(project, "Texture")
    assert flip_of(textures["stone_ddn (normal)"][1]) == 0, "a texture that exists is the user's: the setting does not reach it by a compile (the geometry editor's SetFlipNormalY does)"

    import shutil
    shutil.rmtree(guid_folder(project / "Descriptors", "Texture", textures["stone_ddn (normal)"][0]))
    compile_geom(project)
    textures = virtual(project, "Texture")
    assert flip_of(textures["stone_ddn (normal)"][1]) == 1, "made again, the normal map takes the setting"
    assert flip_of(textures["stone_diff (color)"][1]) == 0, "and a color map has nothing to flip"
    assert flip_of(textures["Flat normal"][1]) == 0, "nor does the flat normal"


def normalize_of(text: str) -> int:
    found = re.search(r'"Texture/Normalize Normals"\s+;bool\s+(\d)', text)
    return int(found[1]) if found else 1                    # (on by default)


def test_normalize_normals_is_on_by_default_and_the_setting_reaches_the_normal_maps_made_from_now_on(project):
    compile_geom(project)
    textures = virtual(project, "Texture")
    assert normalize_of(textures["stone_ddn (normal)"][1]) == 1, "a model's normal maps are normalized by default"

    desc = guid_folder(project / "Descriptors", "GeomStatic", GEOM_GUID) / "Descriptor.txt"
    desc.write_text(desc.read_text().replace("xProperties : 5", "xProperties : 6").replace('"GeomStatic/ImportMaterials/bImport" ;bool 1'
        , '"GeomStatic/ImportMaterials/bImport" ;bool 1\n  "GeomStatic/ImportMaterials/Normalize normals" ;bool 0'))
    compile_geom(project)
    textures = virtual(project, "Texture")
    assert normalize_of(textures["stone_ddn (normal)"][1]) == 1, "a texture that exists is the user's: a compile does not change it"

    import shutil
    shutil.rmtree(guid_folder(project / "Descriptors", "Texture", textures["stone_ddn (normal)"][0]))
    compile_geom(project)
    textures = virtual(project, "Texture")
    assert normalize_of(textures["stone_ddn (normal)"][1]) == 0, "made again, the normal map takes the setting"
    assert flip_of(textures["stone_ddn (normal)"][1]) == 0, "and the other option of the normal map is as it was"
