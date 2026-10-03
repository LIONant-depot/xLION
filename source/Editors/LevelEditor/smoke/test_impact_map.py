"""The tools that make the smoke tests cheaper to use: the impact map (which tests cover which sources), the crash summary the harness adds to a failure, and the command client.

These run without an editor.
"""
import json
import re
import tempfile
from pathlib import Path

import harness
import impact
import pytest

pytestmark = pytest.mark.no_editor

SMOKE = Path(__file__).resolve().parent


def test_every_test_file_is_named_in_the_impact_map():
    """A new test file has to be put in golden/test_impact.json, or `impact.py` would never suggest it."""
    named = {t for _, tests in json.loads(impact.MAP.read_text())["map"] for t in tests}
    files = {p.name for p in SMOKE.glob("test_*.py")}
    missing = sorted(f for f in files if f not in named and f != "test_impact_map.py")
    assert not missing, f"not in golden/test_impact.json: {missing}"


def test_every_test_the_map_names_exists():
    named = {t for _, tests in json.loads(impact.MAP.read_text())["map"] for t in tests if t != "$own"}
    assert not [t for t in named if not (SMOKE / t).is_file()]


def test_a_changed_source_points_to_the_tests_that_cover_it():
    assert "test_engine_copies.py" in impact.impact(["plugins/xlevel.plugin/source/Editor/xlevel_engine_copies.h"])
    assert "test_physics_events.py" in impact.impact(["dependencies/xLIONCore/src/physics/xlioncore_physics_system.h"])
    assert impact.impact(["source/Editors/LevelEditor/smoke/test_play.py"]) == ["test_play.py"], "a test file is its own impact"
    assert impact.impact(["documentation/Editors/engine_copies.md"]) == [], "a document needs no test"


def test_a_failure_of_the_editor_says_how_it_died(tmp_path):
    """The harness adds what the editor wrote about its own death to the error (the assert, and the frames of the editor's code)."""
    (tmp_path / "LevelEditor.trace.log").write_text("\n".join(
        [ "startup: something"
        , "CRT report type=2 message=vector subscript out of range"
        , "CRT stack[0] xeditor::diagnostics::CrtReportHook+0x146 (diagnostics.h:197)"
        , "CRT stack[1] VCrtDbgReportA+0x77f"
        , "CRT stack[2] xecs::system::mgr::Load+0x418 (xecs_system_mgr_inline.h:430)"
        , "CRT stack[3] xlevel::session::session+0xddb (xlevel_session.h:460)"
        , "CRT stack[4] BaseThreadInitThunk+0x17" ]))
    exe = tmp_path / "xLION.exe"
    exe.write_text("")
    summary = harness.Editor(exe).crash_summary()
    assert "vector subscript out of range" in summary
    assert "xecs::system::mgr::Load" in summary and "xlevel::session::session" in summary
    assert "VCrtDbgReportA" not in summary and "BaseThreadInitThunk" not in summary, "only the frames of the editor's own code"
    assert harness.Editor(tmp_path / "nowhere" / "x.exe").crash_summary() == "", "no trace: nothing to add"


def test_the_command_client_documents_how_it_is_used():
    import xcmd
    assert "python xcmd.py" in xcmd.__doc__ and "live.py" in xcmd.__doc__
