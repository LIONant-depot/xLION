"""What the Compilation tab reads out of a compiler's output (dependencies/xresource_pipeline_v2/source/editor/xresource_editor_compile_output.h): the warnings and errors
with the lines that belong to them, and the progress bar, in the grammar the pipeline prints.

The parser is plain text work, so the test compiles dependencies/xresource_pipeline_v2/smoke_test_compile_output.cpp (no editor, no GPU) and runs it.
"""
import os
import subprocess

import pytest

import harness
from harness import REPO

ROOT = REPO / "dependencies" / "xresource_pipeline_v2"
SRC = ROOT / "smoke_test_compile_output.cpp"
OUT = REPO / "Build" / "compile_output"


def build():
    OUT.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        from prefab_bench import VCVARS
        exe = OUT / "smoke_test_compile_output.exe"
        bat = OUT / "build.bat"
        bat.write_text(f'@echo off\r\ncall "{VCVARS}" >nul 2>&1 && cl /nologo /std:c++20 /EHsc /O2 /I"{ROOT}" /I"{REPO}" "{SRC}" /Fe:"{exe}" /Fo:"{OUT}/"\r\n')
        done = subprocess.run(["cmd", "/c", str(bat)], capture_output=True, text=True, cwd=OUT)
    else:
        exe = OUT / "smoke_test_compile_output"
        done = subprocess.run([harness.cxx_compiler(), "-std=gnu++20", "-O2", f"-I{ROOT}", f"-I{REPO}", str(SRC), "-o", str(exe)], capture_output=True, text=True, cwd=OUT)
    assert done.returncode == 0 and exe.is_file(), "the output test did not compile:\n" + (done.stdout + done.stderr)[-3000:]
    return exe


@pytest.mark.no_editor
def test_warnings_errors_and_the_progress_bar_are_read_out_of_the_compilers_output():
    exe = build()
    run = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "all checks passed" in run.stdout
