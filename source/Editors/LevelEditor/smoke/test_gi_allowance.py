"""The host's shared GI allowance per frame (dependencies/xeditor/include/xeditor/gi_allowance.h): the Level's viewport first whatever the render order, the rest for the previews, never a grant of 0.

The rule is pure arithmetic, so the test compiles dependencies/xeditor/smoke_test_gi_allowance.cpp (no editor, no GPU) and runs it.
"""
import os
import subprocess

import pytest

import harness
from harness import REPO

SRC = REPO / "dependencies" / "xeditor" / "smoke_test_gi_allowance.cpp"
INCLUDE = REPO / "dependencies" / "xeditor" / "include"
OUT = REPO / "Build" / "gi_allowance"


def build():
    OUT.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        from prefab_bench import VCVARS
        exe = OUT / "smoke_test_gi_allowance.exe"
        bat = OUT / "build.bat"
        bat.write_text(f'@echo off\r\ncall "{VCVARS}" >nul 2>&1 && cl /nologo /std:c++20 /EHsc /O2 /I"{INCLUDE}" "{SRC}" /Fe:"{exe}" /Fo:"{OUT}/"\r\n')
        done = subprocess.run(["cmd", "/c", str(bat)], capture_output=True, text=True, cwd=OUT)
    else:
        exe = OUT / "smoke_test_gi_allowance"
        done = subprocess.run([harness.cxx_compiler(), "-std=gnu++20", "-O2", f"-I{INCLUDE}", str(SRC), "-o", str(exe)], capture_output=True, text=True, cwd=OUT)
    assert done.returncode == 0 and exe.is_file(), "the allowance test did not compile:\n" + (done.stdout + done.stderr)[-3000:]
    return exe


@pytest.mark.no_editor
def test_the_foreground_comes_first_and_a_grant_is_never_zero():
    exe = build()
    run = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "all checks passed" in run.stdout
