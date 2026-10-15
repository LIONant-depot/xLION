"""The order the pipeline compiles the virtual resources of an owner in (dependencies/xresource_pipeline_v2/source/editor/xresource_editor_virtual_chain.h):
unused ones are never compiled, the others wait for their owner and for the earlier ones of its chain (a Skeleton before the Anim Package that reads its bones).

The rules are plain bookkeeping, so the test compiles dependencies/xresource_pipeline_v2/smoke_test_virtual_chain.cpp (no editor, no GPU) and runs it.
"""
import os
import subprocess

import pytest

import harness
from harness import REPO

ROOT = REPO / "dependencies" / "xresource_pipeline_v2"
SRC = ROOT / "smoke_test_virtual_chain.cpp"
OUT = REPO / "Build" / "virtual_chain"


def build():
    OUT.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        from prefab_bench import VCVARS
        exe = OUT / "smoke_test_virtual_chain.exe"
        bat = OUT / "build.bat"
        bat.write_text(f'@echo off\r\ncall "{VCVARS}" >nul 2>&1 && cl /nologo /std:c++20 /EHsc /O2 /I"{ROOT}" /I"{REPO}" "{SRC}" /Fe:"{exe}" /Fo:"{OUT}/"\r\n')
        done = subprocess.run(["cmd", "/c", str(bat)], capture_output=True, text=True, cwd=OUT)
    else:
        exe = OUT / "smoke_test_virtual_chain"
        done = subprocess.run([harness.cxx_compiler(), "-std=gnu++20", "-O2", f"-I{ROOT}", f"-I{REPO}", str(SRC), "-o", str(exe)], capture_output=True, text=True, cwd=OUT)
    assert done.returncode == 0 and exe.is_file(), "the chain test did not compile:\n" + (done.stdout + done.stderr)[-3000:]
    return exe


@pytest.mark.no_editor
def test_virtual_resources_wait_for_their_owner_and_run_in_the_order_of_the_chain():
    exe = build()
    run = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "all checks passed" in run.stdout
