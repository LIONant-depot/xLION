"""The tools that make the smoke tests cheaper to use: the impact map (which tests cover which sources), the crash summary the harness adds to a failure, and the command client.

These run without an editor.
"""
import re
import tempfile
from pathlib import Path

import harness
import impact
import pytest

pytestmark = pytest.mark.no_editor

SMOKE = Path(__file__).resolve().parent


def test_every_test_file_is_in_the_generated_map():
    """The map is built from the code (R97): every test file is in it, with the commands it drives; nothing kept by hand."""
    m = impact.load_map()
    assert set(m["tests"]) == {p.name for p in SMOKE.glob("test_*.py")}
    assert "OpenLevel" in m["commands"] and "OpenLevel" in m["tests"]["test_engine_copies.py"]


def test_what_the_map_cannot_place():
    """an ignore file needs no test; a build file or shader the map cannot place gets the core set (the nightly full run is the net)"""
    assert impact.tests_for(".gitignore") == []
    assert impact.tests_for("source/Editors/LevelEditor/CMakeLists.txt") is impact.CORE


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
