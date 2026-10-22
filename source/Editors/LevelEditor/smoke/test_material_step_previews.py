"""In-node rendered previews on the Material Stack canvas (stack_canvas.md 10.2, 13): a computed step on the screen shows its output, made by
compiling a copy of the material, and makes it again only when something upstream of it changes. The example material "One Texture" is opened
in the Debug window editor, one literal is changed and the material is closed without saving. Windows only.
"""
import os
import re
import time

import pytest

import harness
from harness import Editor
from test_material_stack_canvas import Canvas

pytestmark = [pytest.mark.no_editor, pytest.mark.needs_window, pytest.mark.skipif(os.name != "nt", reason="drives the Windows editor window")]


def previews(cv: Canvas) -> dict[str, tuple[str, int]]:
    """step guid -> (current|stale|none|failed, times made)"""
    return {g: (s, int(n)) for g, s, n in re.findall(r"^([0-9A-F]{16}) (\w+) (\d+)", cv.C("StepPreviews"), re.M)}


def guid(cv: Canvas, name: str) -> str:
    return next(g for g, n, _ in cv.steps() if n == name)


def wait_current(cv: Canvas, step: str, renders: int, timeout: float = 60) -> dict:
    end = time.time() + timeout
    while time.time() < end:
        p = previews(cv)
        if p.get(step, ("", 0))[0] == "current" and p[step][1] >= renders:
            return p
        cv.ed._frames(10)
    pytest.fail(f"{step} not made {renders} time(s): {cv.C('StepPreviews')}")


def test_rendered_previews_follow_their_inputs():
    ed = Editor(harness.DEFAULT_EXE)
    ed.start()
    cv = Canvas(ed)
    try:
        assert cv.C("StepPreviews -On true") == "StepPreviews: on"
        add, inputs = guid(cv, "Vec4_Add"), guid(cv, "Input__Vertex_Variants")
        cv.C("SelectStep -Node @Vec4_Add")                 # on the screen: it asks for its picture
        p = wait_current(cv, add, 1)
        assert p[inputs][0] == "current", p                # a source step renders too
        before = p[inputs][1]

        cv.node("Texture", "Broken", "Steps")              # an unwired Texture step: the material no longer compiles, a copy of what Add reads does
        cv.E('SetNodeProperty -Node @Vec2 -Path "node/Params[G:0]/Float" -Value 0.1')
        p = wait_current(cv, add, 2)                       # upstream changed: made again
        assert p[inputs] == ("current", before), p         # not upstream: left alone
        broken = guid(cv, "Broken")
        assert not [g for g, (s, _) in p.items() if s == "failed" and g != broken], p
    finally:
        try:
            cv.close()
        finally:
            ed.stop()
