"""Actions: keys, menu items and toolbar buttons are generated from the editors' xproperty descriptions (dependencies/actions.imgui).

PressKeys resolves a chord exactly like a real key press, so every binding can be tested without OS keyboard input.
None of these need an open Level: the editor without a Level has its own (never saved) Level editor, so its actions are live.
"""
import time

import pytest

from test_resource_editors import RESOURCE_EDITOR_TYPES, _open_and_check, with_known_issues


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


def test_level_entity_and_play_actions_say_why_they_cannot_run(editor):
    a = actions(editor)
    expected = {"Level/Entity/Delete": ("Delete", "nothing selected"), "Level/Entity/Rename": ("F2", "nothing selected"),
                "Level/Stop": ("Shift+F5", "not playing")}
    for path, (keys, why) in expected.items():
        assert path in a, f"{path} is not live; got {sorted(a)}"
        assert a[path] == (keys, why), f"{path}: {a[path]}"
    assert a["Level/Play"][0] == "F5"                 # never pressed here: it would really start playing
    assert editor.cmd("RunAction -Path Level/Entity/Delete").endswith("did not run: nothing selected")


@pytest.mark.parametrize("type_name", with_known_issues(RESOURCE_EDITOR_TYPES))
def test_every_resource_editor_gets_the_editor_actions(editor, type_name):
    """Opening any resource editor makes Editor/Save, Undo, Redo, Compile live, with the same keys in every editor."""
    guid, _ = _open_and_check(editor, type_name)
    try:
        time.sleep(0.7)                                   # the editor registers its scopes while it draws
        a = actions(editor)
        for path, keys in {"Editor/Save": "Ctrl+S", "Editor/Undo": "Ctrl+Z", "Editor/Redo": "Ctrl+Y", "Editor/Compile": "F5", "Editor/Feedback": "F6"}.items():
            assert path in a and a[path][0] == keys, f"{type_name}: {path} -> {a.get(path)}; live: {sorted(a)}"
        assert a["Editor/Save"][1] == "no changes to save" and a["Editor/Undo"][1] == "nothing to undo"
        # each editor's own keys, besides the shared Editor/... ones
        for path, keys in {"Texture": {"Texture/Preview/LightFollowsCamera": "L"}, "GeomStatic": {"GeomStatic/Preview/LightFollowsCamera": "F"}
                           , "AnimPackage": {"AnimPackage/Preview/PlayPause": "P"}}.get(type_name, {}).items():
            assert path in a and a[path][0] == keys, f"{type_name}: {path} -> {a.get(path)}; live: {sorted(a)}"
    finally:
        editor.cmd(f"CloseResourceEditor -Asset {guid}")


def test_list_actions_lists_each_action_once(editor):
    paths = [l.split("\t")[0] for l in editor.cmd("ListActions").splitlines() if l.strip()]
    assert len(paths) == len(set(paths)), f"duplicates: {sorted(p for p in set(paths) if paths.count(p) > 1)}"


def test_the_keyboard_overlay_and_palette_are_actions(editor):
    a = actions(editor)
    assert a["Host/Keyboard/Show"][0] == "F1"
    assert a["Host/Palette/Open"][0] == "Ctrl+Shift+P"
    assert "Host/Keyboard/Show" in editor.cmd("PressKeys -Keys F1")
    editor.cmd("PressKeys -Keys F1")                      # closes it again


def test_keys_of_editors_that_are_not_open_can_be_configured(editor):
    """The keymap knows every editor's actions from the start (no editor of that type is open here): the Editor/... keys of the
    resource editors and the Assets/... keys of the asset browser can be rebound before the editor is ever opened."""
    try:
        assert editor.cmd("BindKey -Path Editor/Compile -Keys F7", allow_disk=True) == "Editor/Compile is bound to F7"
        assert editor.cmd("BindKey -Path Assets/Delete -Keys Ctrl+Delete", allow_disk=True) == "Assets/Delete is bound to Ctrl+Delete"
    finally:
        editor.cmd("ResetKey -Path Editor/Compile", allow_disk=True)
        editor.cmd("ResetKey -Path Assets/Delete", allow_disk=True)
    assert "ActionProblems" in editor.commands()
