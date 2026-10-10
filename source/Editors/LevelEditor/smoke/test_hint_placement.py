"""Where a hint opens (dependencies/xeditor/include/xeditor/hint_placement.h): beside the cursor, and ALWAYS completely inside the window of the app, so it is never given a window of its own.

The rule is pure arithmetic, so the test compiles dependencies/xeditor/smoke_test_hint_placement.cpp (no editor, no GPU) and runs it.
"""
import os
import subprocess

import pytest

import harness
from harness import REPO

SRC = REPO / "dependencies" / "xeditor" / "smoke_test_hint_placement.cpp"
INCLUDE = REPO / "dependencies" / "xeditor" / "include"
OUT = REPO / "Build" / "hint_placement"


def build():
    OUT.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        from prefab_bench import VCVARS
        exe = OUT / "smoke_test_hint_placement.exe"
        bat = OUT / "build.bat"
        bat.write_text(f'@echo off\r\ncall "{VCVARS}" >nul 2>&1 && cl /nologo /std:c++20 /EHsc /O2 /I"{INCLUDE}" "{SRC}" /Fe:"{exe}" /Fo:"{OUT}/"\r\n')
        done = subprocess.run(["cmd", "/c", str(bat)], capture_output=True, text=True, cwd=OUT)
    else:
        exe = OUT / "smoke_test_hint_placement"
        done = subprocess.run([harness.cxx_compiler(), "-std=gnu++20", "-O2", f"-I{INCLUDE}", str(SRC), "-o", str(exe)], capture_output=True, text=True, cwd=OUT)
    assert done.returncode == 0 and exe.is_file(), "the placement test did not compile:\n" + (done.stdout + done.stderr)[-3000:]
    return exe


@pytest.mark.no_editor
def test_a_hint_opens_beside_the_cursor_and_always_inside_the_window():
    exe = build()
    run = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "all checks passed" in run.stdout
