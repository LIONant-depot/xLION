"""The two ECS gates: the editor may only use the registry of the one core through its own import less and less (ecs_gate.py, documentation/Editors/ecs_link_gate.md).

The editor does not need to be running for any of this. The link gate builds the target xLION_ecs_gate (the headless editor linked without LIONCore.dll and LIONRender.dll): that takes as long as
a build of the editor the first time and is quick when nothing changed.
"""
import json

import ecs_gate


def test_the_editor_uses_no_more_of_the_registry_than_the_baseline():
    """A bit id, a pool, the registry itself ... in the code of the editor is a place that silently talks to the core the exe imports, not to the copy of the core the world belongs to."""
    baseline = json.loads(ecs_gate.SCAN_BASELINE.read_text())
    grown, shrunk = ecs_gate.compare_scan(ecs_gate.scan(), baseline)
    assert not grown, ("the editor reaches the registry in more places than before (go through the xECSEditor interface, or if it really is less: python ecs_gate.py scan --update):\n  " + "\n  ".join(grown))


def test_the_editor_takes_no_more_from_the_engine_dlls_than_the_baseline():
    """Linked without LIONCore.dll and LIONRender.dll, the editor has these symbols unresolved: each is a call or a static that goes to the one core the exe imports."""
    symbols = ecs_gate.link_gate()
    baseline = ecs_gate.read_link_baseline()
    new = [s for s in symbols if s not in baseline]
    assert not new, "the editor now takes more from the engine DLLs than before (python ecs_gate.py link --update when it is less):\n  " + "\n  ".join(new)


# ---- the gates themselves: they have to see what they are there for ---------------------------------------------------------------------------------------------------------------

def test_the_scan_sees_code_and_ignores_comments_and_strings():
    code = ecs_gate.strip_comments_and_strings('int a = info_v<T>.m_BitID; // m_pPool in a comment\n/* s_Registry\n in a block */ const char* s = "getEntityDetails"; char c = \'m\';\nint b = m_pPool;\n')
    seen = [m[1] for m in ecs_gate.TOKEN_RE.finditer(code)]
    assert seen == ["info_v", "m_BitID", "m_pPool"], seen


def test_the_scan_compares_per_file_and_per_token():
    baseline = {"a.h": {"m_BitID": 2}}
    assert ecs_gate.compare_scan({"a.h": {"m_BitID": 2}}, baseline) == ([], [])
    grown, shrunk = ecs_gate.compare_scan({"a.h": {"m_BitID": 3}}, baseline)
    assert grown == ["a.h: m_BitID 2 -> 3"] and not shrunk, "more of the same"
    grown, _ = ecs_gate.compare_scan({"a.h": {"m_BitID": 2}, "b.h": {"info_v": 1}}, baseline)
    assert grown == ["b.h: info_v 0 -> 1"], "a file that never used a token starts to"
    grown, shrunk = ecs_gate.compare_scan({"a.h": {"m_BitID": 1}}, baseline)
    assert not grown and shrunk == ["a.h: m_BitID 2 -> 1"], "less is good news"


def test_the_scan_covers_the_editor_and_not_the_tests():
    seen = [f.relative_to(ecs_gate.REPO).as_posix() for f in ecs_gate.scanned_files()]          # every file read, whether it uses the tokens or not (a clean editor has none that does)
    assert any(f.startswith("plugins/xscene.plugin/") for f in seen) and any(f.startswith("plugins/xlevel.plugin/") for f in seen)
    assert any(f.startswith("source/Editors/LevelEditor/") for f in seen)
    assert not any("/smoke/" in f for f in seen)
