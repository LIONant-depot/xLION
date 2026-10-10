"""The hover card of a resource (dependencies/xeditor/include/xeditor/hint.h, growing_card) driven with ImGui itself, with no window and no GPU: the card must be completely inside the window in
every frame it is visible, on its first hover (it starts small and grows) and on the next ones (its size is known: it opens at that size, in the right place, from the first frame).

The test compiles dependencies/xeditor/smoke_test_hint_card.cpp with the sources of ImGui and runs it.
"""
import os
import subprocess

import pytest

import harness
from harness import REPO

SRC = REPO / "dependencies" / "xeditor" / "smoke_test_hint_card.cpp"
IMGUI = REPO / "dependencies" / "imgui"
IMGUI_SOURCES = [IMGUI / name for name in ("imgui.cpp", "imgui_draw.cpp", "imgui_tables.cpp", "imgui_widgets.cpp")]
OUT = REPO / "Build" / "hint_card"


def build():
    OUT.mkdir(parents=True, exist_ok=True)
    sources = [SRC, *IMGUI_SOURCES]
    if os.name == "nt":
        from prefab_bench import VCVARS
        exe = OUT / "smoke_test_hint_card.exe"
        srcs = " ".join(f'"{s}"' for s in sources)
        bat = OUT / "build.bat"
        bat.write_text(f'@echo off\r\ncall "{VCVARS}" >nul 2>&1 && cl /nologo /std:c++20 /EHsc /O1 /utf-8 /DIMGUI_DEFINE_MATH_OPERATORS /I"{REPO}" /I"{IMGUI}" {srcs} /Fe:"{exe}" /Fo:"{OUT}/"\r\n')
        done = subprocess.run(["cmd", "/c", str(bat)], capture_output=True, text=True, cwd=OUT)
    else:
        exe = OUT / "smoke_test_hint_card"
        platform = REPO / "source" / "Platform"
        shim_alias = harness.DEFAULT_EXE.parent / "linux_win32_shim_alias"
        cmd = ["clang++", "-std=gnu++20", "-O1", "-w", "-DIMGUI_DEFINE_MATH_OPERATORS", f"-include{platform / 'xlion_platform_compat_linux.h'}", "-fms-extensions", "-fdeclspec",
               f"-I{platform / 'linux_win32_shim'}", *([f"-I{shim_alias}"] if shim_alias.is_dir() else []), f"-I{REPO}", f"-I{IMGUI}", *[str(s) for s in sources], "-o", str(exe)]
        done = subprocess.run(cmd, capture_output=True, text=True, cwd=OUT)
    assert done.returncode == 0 and exe.is_file(), "the card test did not compile:\n" + (done.stdout + done.stderr)[-4000:]
    return exe


@pytest.mark.no_editor
def test_the_card_is_inside_the_window_on_every_frame_and_a_known_one_opens_at_its_size():
    exe = build()
    run = subprocess.run([str(exe)], capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "all checks passed" in run.stdout
