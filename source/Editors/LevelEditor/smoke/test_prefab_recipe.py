"""Prefab instances are recipes, in the engine (documentation/Editors/prefabs_plan.md, phase 3): compiles dependencies/xECSV2/smoke_test_prefab_recipe.cpp in Debug (asserts on) and runs it.

Derived member ids; an instance saved as one file (its recipe) and spawned again with the same ids, values and references; a prefab that gains, reorders
and loses members; nested instances; Apply. No editor: the engine alone, about a minute to compile.
"""
import subprocess

import pytest

from prefab_bench import REPO, build

pytestmark = pytest.mark.no_editor


def test_prefab_recipe_engine_checks():
    exe = build(debug=True, src=REPO / "dependencies" / "xECSV2" / "smoke_test_prefab_recipe.cpp")
    r = subprocess.run([str(exe)], capture_output=True, text=True, cwd=exe.parent, timeout=300)
    report = "\n".join(l for l in r.stdout.splitlines() if l.startswith(("STEP", "FAIL", "ALL")) or "CHECK" in l)
    assert r.returncode == 0 and "ALL CHECKS PASSED" in r.stdout, f"{report}\n--- stderr (asserts) ---\n{r.stderr[-3000:]}"
    assert "Assertion" not in r.stderr and "assert" not in r.stderr.lower(), r.stderr[-3000:]
