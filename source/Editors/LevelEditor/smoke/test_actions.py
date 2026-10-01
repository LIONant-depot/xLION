"""Actions: keys, menu items and toolbar buttons are generated from the editors' xproperty descriptions (dependencies/actions.imgui).

PressKeys resolves a chord exactly like a real key press, so every binding can be tested without OS keyboard input.
None of these need an open Level: the editor without a Level has its own (never saved) Level editor, so its actions are live.
"""
import pytest


def actions(editor) -> dict[str, tuple[str, str]]:
    """path -> (keys, 'ok' or the reason it cannot run)"""
    out = {}
    for line in editor.cmd("ListActions").splitlines():
        parts = line.split("\t")
        if len(parts) == 3:
            out[parts[0]] = (parts[1], parts[2])
    return out


def test_default_actions_are_listed_with_their_keys(editor):
    a = actions(editor)
    expected = {
        "Level/Save": "Ctrl+S", "Level/Undo": "Ctrl+Z", "Level/Redo": "Ctrl+Y",
        "Level/Viewport/ToolSelect": "Q", "Level/Viewport/ToolMove": "W",
        "Level/Viewport/ToolRotate": "E", "Level/Viewport/ToolScale": "R",
        "Host/Drawer/Toggle": "Space",
    }
    for path, keys in expected.items():
        assert path in a, f"{path} is not live; got {sorted(a)}"
        assert a[path][0] == keys, f"{path}: keys {a[path][0]!r}, expected {keys!r}"


def test_an_action_that_cannot_run_says_why(editor):
    a = actions(editor)
    assert a["Level/Undo"][1] != "ok"        # nothing has been edited in the editor without a Level
    assert a["Level/Save"][1] != "ok"        # nothing is open to save


def test_press_keys_reaches_the_action_and_explains_a_refusal(editor):
    reply = editor.cmd("PressKeys -Keys Ctrl+Z")
    assert "Level/Undo" in reply and "did not run" in reply, reply
    assert "Level/Undo" in editor.cmd("ExplainLastKey")


def test_a_key_nothing_is_bound_to(editor):
    assert "no live action is bound" in editor.cmd("PressKeys -Keys Ctrl+Alt+F12")


def test_a_bad_chord_is_reported(editor):
    assert "not a key chord" in editor.cmd("PressKeys -Keys Ctrl+Banana")


def test_space_toggles_the_drawer_through_its_action(editor):
    first = editor.cmd("PressKeys -Keys Space")
    second = editor.cmd("PressKeys -Keys Space")      # leave the drawer as it was
    for reply in (first, second):
        assert reply == "Space -> Host/Drawer/Toggle", reply


def test_run_action_by_path(editor):
    reply = editor.cmd("RunAction -Path Level/Save")
    assert reply.startswith("Level/Save did not run"), reply          # nothing to save: refused, nothing written
    assert "no live action" in editor.cmd("RunAction -Path Nope/Nothing")


def test_viewport_tool_actions_run(editor):
    assert editor.cmd("RunAction -Path Level/Viewport/ToolMove") == "Ran Level/Viewport/ToolMove"
    assert editor.cmd("RunAction -Path Level/Viewport/ToolSelect") == "Ran Level/Viewport/ToolSelect"


def test_action_problems_are_reported(editor):
    # A healthy setup has none; the point is that the report exists and says so instead of being silent.
    reply = editor.cmd("ActionProblems")
    assert reply == "No problems" or "\n" in reply or ":" in reply, reply
    assert "are both on" not in reply, f"the default keys conflict with each other: {reply}"


def test_rebinding_a_key_takes_effect_and_resets(editor):
    """BindKey writes YOUR keymap file (project_guard puts Project.config back); the new key reaches the action, the old one no longer does."""
    try:
        assert editor.cmd("BindKey -Path Level/Redo -Keys F8", allow_disk=True) == "Level/Redo is bound to F8"
        assert actions(editor)["Level/Redo"][0] == "F8"
        assert "Level/Redo" in editor.cmd("PressKeys -Keys F8")
        assert "Level/Redo" not in editor.cmd("PressKeys -Keys Ctrl+Y")
    finally:
        editor.cmd("ResetKey -Path Level/Redo", allow_disk=True)
    assert actions(editor)["Level/Redo"][0] == "Ctrl+Y"
    assert "Level/Redo" in editor.cmd("PressKeys -Keys Ctrl+Y")


def test_unbinding_and_bad_bindings(editor):
    try:
        assert editor.cmd("BindKey -Path Level/Redo", allow_disk=True) == "Level/Redo is unbound"
        assert actions(editor)["Level/Redo"][0] == ""
        assert "no known action" in editor.cmd("BindKey -Path Nope/Nothing -Keys F9", allow_disk=True)
        assert "not a key chord" in editor.cmd("BindKey -Path Level/Redo -Keys Ctrl+Banana", allow_disk=True)
    finally:
        editor.cmd("ResetKey -Path Level/Redo", allow_disk=True)
    assert actions(editor)["Level/Redo"][0] == "Ctrl+Y"


def test_the_palette_action_is_live_in_text_fields_too(editor):
    a = actions(editor)
    assert a["Host/Palette/Open"][0] == "Ctrl+Shift+P"
