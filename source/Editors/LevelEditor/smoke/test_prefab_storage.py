"""Prefab storage in the engine (documentation/Editors/prefabs_plan.md, phase 1): compiles dependencies/xECSV2/smoke_test_prefab_storage.cpp in Debug (asserts on) and runs it.

A prefab is stored as a scene; a group whose members reference each other becomes a prefab whose references point at its own members (phase 0, finding 2); names; the rules Save checks;
the old one-file format still read and converted. No editor: the engine alone, about a minute to compile.
"""
import subprocess

import pytest

from prefab_bench import REPO, build

pytestmark = pytest.mark.no_editor


def test_prefab_storage_engine_checks():
    exe = build(debug=True, src=REPO / "dependencies" / "xECSV2" / "smoke_test_prefab_storage.cpp")
    r = subprocess.run([str(exe)], capture_output=True, text=True, cwd=exe.parent, timeout=300)
    report = "\n".join(l for l in r.stdout.splitlines() if l.startswith(("STEP", "FAIL", "ALL", "(a refusal")) or "CHECK" in l)
    assert r.returncode == 0 and "ALL CHECKS PASSED" in r.stdout, f"{report}\n--- stderr (asserts) ---\n{r.stderr[-3000:]}"
    assert "Assertion" not in r.stderr and "assert" not in r.stderr.lower(), r.stderr[-3000:]
