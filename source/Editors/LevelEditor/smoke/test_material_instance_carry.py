"""Changing the material of a Material Instance: the textures the person assigned go to the slots of the new material that have the same name
(plugins/xmaterial_instance.plugin/source/xmaterial_instance_carry.h). Plain matching of names, so the test compiles plugins/xmaterial_instance.plugin/smoke_test_carry.cpp (no editor, no GPU) and runs it.
"""
import os
import subprocess

import pytest

import harness
from harness import REPO

ROOT = REPO / "plugins" / "xmaterial_instance.plugin"
SRC = ROOT / "smoke_test_carry.cpp"
OUT = REPO / "Build" / "material_instance_carry"


def build():
    OUT.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        from prefab_bench import VCVARS
        exe = OUT / "smoke_test_material_instance_carry.exe"
        bat = OUT / "build.bat"
        bat.write_text(f'@echo off\r\ncall "{VCVARS}" >nul 2>&1 && cl /nologo /std:c++20 /EHsc /O2 /I"{ROOT}" /I"{REPO}" "{SRC}" /Fe:"{exe}" /Fo:"{OUT}/"\r\n')
        done = subprocess.run(["cmd", "/c", str(bat)], capture_output=True, text=True, cwd=OUT)
    else:
        exe = OUT / "smoke_test_material_instance_carry"
        done = subprocess.run([harness.cxx_compiler(), "-std=gnu++20", "-O2", f"-I{ROOT}", f"-I{REPO}", str(SRC), "-o", str(exe)], capture_output=True, text=True, cwd=OUT)
    assert done.returncode == 0 and exe.is_file(), "the carry test did not compile:\n" + (done.stdout + done.stderr)[-3000:]
    return exe


@pytest.mark.no_editor
def test_the_textures_the_person_assigned_follow_the_names_of_the_slots_to_the_new_material():
    exe = build()
    run = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "all checks passed" in run.stdout
