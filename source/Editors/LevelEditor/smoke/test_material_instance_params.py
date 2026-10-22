"""Material instances v2 (documentation/material_contract.md sections 5, 6, 9; acceptance tests 3, 7 and 8): the descriptor (an old v1 file read as overrides, a round trip that
keeps an unknown id) and the instance compiler (parents resolve, orphans and clamping are reported, a cycle fails, a material compiled again with another layout changes what an
instance carries and what it depends on). No editor: plugins/xmaterial_instance.plugin/smoke_test_instance.cpp makes a small project in a temp folder (the material's layout and
template as its compiler leaves them, a few instances) and the real instance compiler runs on it. Windows only: the compiler is the one the project built.
"""
import os
import re
import subprocess

import pytest

from harness import REPO

ROOT = REPO / "plugins" / "xmaterial_instance.plugin"
SRC = ROOT / "smoke_test_instance.cpp"
OUT = REPO / "Build" / "material_instance_params"
COMPILER = ROOT / "build" / "xmaterial_instance_compiler.vs2022" / "Debug" / "xmaterial_instance_compiler.exe"

pytestmark = [pytest.mark.no_editor, pytest.mark.skipif(os.name != "nt", reason="drives the Windows build of the instance compiler")]

RED, REDROUGH, OLD, ORPHAN, CYCA, TEX, DSOFF = 0x1001, 0x1003, 0x1005, 0x1007, 0x1009, 0x100D, 0x1011


def build():
    from prefab_bench import VCVARS
    OUT.mkdir(parents=True, exist_ok=True)
    exe = OUT / "smoke_test_instance.exe"
    d = REPO / "dependencies"
    includes = " ".join(f'/I"{d / n}"' for n in ("xerr", "xtextfile", "xcmdline", "xresource_guid", "xproperty", "xresource_pipeline_v2", "xresource_mgr", "xstrtool", "xserializer", "xfile", "xcompression", "zstd"))
    sources = " ".join(f'"{d / p}"' for p in ("xtextfile/source/xtextfile.cpp", "xstrtool/source/xstrtool.cpp", "xfile/source/xfile.cpp"))
    bat = OUT / "build.bat"
    bat.write_text(f'@echo off\r\ncall "{VCVARS}" >nul 2>&1 && cl /nologo /std:c++latest /EHsc /Zc:preprocessor /D_ITERATOR_DEBUG_LEVEL=0 /DUNICODE /D_UNICODE /I"{REPO}" {includes} "{SRC}" {sources} /Fe:"{exe}" /Fo:"{OUT}/"\r\n')
    done = subprocess.run(["cmd", "/c", str(bat)], capture_output=True, text=True, cwd=OUT)
    assert done.returncode == 0 and exe.is_file(), "the instance test did not compile:\n" + (done.stdout + done.stderr)[-3000:]
    return exe


@pytest.fixture(scope="module")
def exe():
    return build()


def run(exe, *args):
    return subprocess.run([str(exe), *map(str, args)], capture_output=True, text=True, timeout=60)


def compile_instance(project, guid):
    """Compiles one instance with the real compiler: (exit code, its output)."""
    desc = rf"Descriptors\MaterialInstance\{guid & 0xff:02X}\{(guid >> 8) & 0xff:02X}\{guid:X}.desc"
    done = subprocess.run([str(COMPILER), "-PROJECT", str(project), "-OPTIMIZATION", "O1", "-DEBUG", "D0", "-DESCRIPTOR", desc, "-OUTPUT", str(project / "Cache" / "Resources" / "Platforms" / "WINDOWS")],
                          capture_output=True, text=True, timeout=120)
    return done.returncode, done.stdout + done.stderr


def block(output):
    m = re.search(r"layout ([0-9A-F]{16}): block of (\d+) bytes:([0-9. e+-]*)", output)
    assert m, output
    return m[1], int(m[2]), [float(v) for v in m[3].split()]


def textures(output):
    m = re.search(r"Textures:((?: [0-9A-F]{16})*)", output)
    assert m, output
    return [int(v, 16) for v in m[1].split()]


def test_a_v1_file_is_read_as_overrides_and_an_unknown_id_survives_a_round_trip(exe, tmp_path):
    assert run(exe, "fixture", tmp_path).returncode == 0
    done = run(exe, "descriptor", tmp_path)
    assert done.returncode == 0 and "all checks passed" in done.stdout, done.stdout + done.stderr


def test_instances_resolve_through_their_parents_and_report_what_is_wrong(exe, tmp_path):
    assert run(exe, "fixture", tmp_path).returncode == 0
    project = tmp_path / "t.lionprj"

    # test 3: MI_RedRough takes Tint from MI_Red and its own Roughness; MI_Red alone has the material's Roughness
    code, text = compile_instance(project, REDROUGH)
    assert code == 0, text
    assert block(text)[1:] == (32, [1, 0, 0, 1, 0.9, 0, 0, 0]) and textures(text) == [0x7001, 0x7003]
    code, text = compile_instance(project, RED)
    assert code == 0 and block(text)[2] == [1, 0, 0, 1, 0.5, 0, 0, 0], text

    # the instance depends on its parent, its material, and the layout and template of the material
    log = next((project / "Cache" / "Resources" / "Logs" / "MaterialInstance").rglob("1003.log")) / "dependencies.txt"
    deps = log.read_text()
    assert "Descriptors/MaterialInstance/01/10/1001.desc/Descriptor.txt" in deps and "C001.log/MaterialLayout.txt" in deps and "C001.log/MaterialInstance.txt" in deps
    assert "#1001 #B673C5DA4A4A70AD" in deps                                  # the parent as a resource

    # test 8: the v1 instance with a changed albedo compiles with that texture; the slot the instance did not touch keeps the material's
    code, text = compile_instance(project, OLD)
    assert code == 0 and textures(text) == [0x7001, 0x7005], text

    # a texture set by a parent reaches its children
    code, text = compile_instance(project, TEX)
    assert code == 0 and textures(text) == [0x7001, 0x7007], text

    # orphans are reported and kept, an out-of-range value is clamped to the declaration's range
    code, text = compile_instance(project, ORPHAN)
    assert code == 0 and "W_ORPHAN_ID: parameter 0000000000000999" in text and "W_CLAMPED: parameter 0000000000000020" in text, text
    assert block(text)[2][4] == 1.0

    # a cycle fails, with its code
    code, text = compile_instance(project, CYCA)
    assert code != 0 and "E_CHAIN_CYCLE" in text, text


def test_a_material_compiled_with_another_layout_changes_what_the_instance_carries(exe, tmp_path):
    """Test 7, the compiler's half: the instance has the hash of the layout it was compiled against (the renderer compares it with the material's and draws the constant material
    on a mismatch, E_LAYOUT_STALE); compiled again after the material, it has the new one, and the block follows the new layout."""
    assert run(exe, "fixture", tmp_path).returncode == 0
    project = tmp_path / "t.lionprj"
    code, text = compile_instance(project, REDROUGH)
    assert code == 0, text
    before = block(text)

    assert run(exe, "fixture", tmp_path, "new-param").returncode == 0           # the material gains a parameter: another layout, another hash
    code, text = compile_instance(project, REDROUGH)
    assert code == 0, text
    after = block(text)
    assert before[0] != after[0], "the hash must follow the layout"
    assert after[2] == [1, 0, 0, 1, 0.9, 0, 0, 0] or after[2][:5] == [1, 0, 0, 1, 0.9], "the values stay, in the new layout"


def test_double_sided_is_the_first_of_the_chain_that_sets_it(exe, tmp_path):
    """render_settings_plan.md part three: an instance's Double Sided (Inherit / On / Off) goes into its compiled file; Inherit takes its parent's, then the material's."""
    assert run(exe, "fixture", tmp_path).returncode == 0
    project = tmp_path / "t.lionprj"
    code, text = compile_instance(project, RED)
    assert code == 0 and "Double Sided: on (the instance's)" in text, text
    code, text = compile_instance(project, REDROUGH)
    assert code == 0 and "Double Sided: on (the instance's)" in text, "a child that does not set it takes its parent's " + text
    code, text = compile_instance(project, DSOFF)
    assert code == 0 and "Double Sided: off (the instance's)" in text, "a child that sets it wins over its parent " + text
    code, text = compile_instance(project, ORPHAN)
    assert code == 0 and "Double Sided:" not in text, "no instance of the chain sets it: the material's " + text
