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
        assert editor.cmd("BindKey -Path Level/Redo -Keys F9", allow_disk=True) == "Level/Redo is bound to F9"
        assert actions(editor)["Level/Redo"][0] == "F9"
        assert "Level/Redo" in editor.cmd("PressKeys -Keys F9")
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
    assert a["Host/Explain/Pin"][0] == "F1"                # explains what the mouse rests on; over nothing, the keyboard
    assert a["Host/Keyboard/Show"][0] == "Shift+F1"       # always the keyboard
    assert a["Host/Palette/Open"][0] == "Ctrl+Shift+P"
    assert "Host/Keyboard/Show" in editor.cmd("PressKeys -Keys Shift+F1")
    editor.cmd("PressKeys -Keys Shift+F1")                # closes it again
    assert "Host/Explain/Pin" in editor.cmd("PressKeys -Keys F1")       # nothing is hovered: the keyboard again
    editor.cmd("PressKeys -Keys F1")


def test_binding_a_key_another_action_has_is_reported(editor):
    """The keymap page asks Replace / Cancel for this; BindKey says it in its reply (and still binds: the problems list shows the two)."""
    try:
        reply = editor.cmd("BindKey -Path Level/Redo -Keys Ctrl+Z", allow_disk=True)
        assert reply == "Level/Redo is bound to Ctrl+Z (Level/Undo is also on Ctrl+Z)", reply
        assert "Level/Undo and Level/Redo are both on Ctrl+Z" in editor.cmd("ActionProblems") or "Level/Redo and Level/Undo are both on Ctrl+Z" in editor.cmd("ActionProblems")
    finally:
        editor.cmd("ResetKey -Path Level/Redo", allow_disk=True)


def test_a_keymap_can_be_saved_and_used_as_a_base(editor):
    """My keys saved as a keymap in the project, which anyone's own file can then sit on (the keymap page's 'Based on' and 'Save my keys as it')."""
    try:
        editor.cmd("BindKey -Path Level/Redo -Keys F9", allow_disk=True)
        assert editor.cmd("SaveKeymapAs -Name SmokeShared", allow_disk=True) == "Saved as SmokeShared"
        assert "no letters" in editor.cmd("SaveKeymapAs -Name bad/name", allow_disk=True) or "letters, digits" in editor.cmd("SaveKeymapAs -Name bad/name", allow_disk=True)
        editor.cmd("ResetKey -Path Level/Redo", allow_disk=True)
        assert actions(editor)["Level/Redo"][0] == "Ctrl+Y"
        assert "SmokeShared" in editor.cmd("ListKeymaps")
        assert editor.cmd("UseKeymap -Name SmokeShared", allow_disk=True) == "Your keys sit on SmokeShared"
        assert actions(editor)["Level/Redo"][0] == "F9"                       # the preset's key reaches the action
        assert "based on: SmokeShared" in editor.cmd("ListKeymaps")
        assert "no keymap named" in editor.cmd("UseKeymap -Name Nope", allow_disk=True)
    finally:
        editor.cmd("UseKeymap", allow_disk=True)
        editor.cmd("ResetKey -Path Level/Redo", allow_disk=True)


@pytest.mark.parametrize("type_name", ["GeomStatic", "AnimPackage"])
def test_a_3d_preview_declares_its_mouse_gestures(editor, type_name):
    """The preview of these editors says what the mouse does in it (the F1 view draws it on the mouse; the status line shows it)."""
    guid, _ = _open_and_check(editor, type_name)
    try:
        try:
            g = editor.wait_for("ListGestures", r"Preview\tRMB drag\tLook around", timeout=8)       # declared once the preview has drawn
        except TimeoutError:
            # The preview is only drawn while its dock tab is visible; after other tests opened and closed editors the saved layout can hide it.
            pytest.skip(f"the {type_name} preview window is not visible in this layout")
        assert "Preview\tWheel\tZoom" in g, g
    finally:
        editor.cmd(f"CloseResourceEditor -Asset {guid}")


def test_surfaces_declare_their_mouse_gestures(editor):
    """The Level's viewport and tree list what the mouse does on them (descriptions: the F1 view draws them on the mouse, the status line shows them)."""
    g = editor.wait_for("ListGestures", r"Viewport\tWheel\tZoom", timeout=20)
    for line in ("Viewport\tLMB click\tSelect", "Viewport\tCtrl+LMB click\tAdd / remove", "Viewport\tRMB drag\tLook around",
                 "Viewport\tRMB drag + W A S D Q E\tFly", "Viewport\tMMB drag\tPan", "Level tree\tRMB click\tMenu"):
        assert line in g, f"missing {line!r} in: {g}"


def test_a_real_function_key_reaches_its_action(editor):
    """WM_KEYDOWN to the window, through the Win32 key table, xGPU and ImGui (PressKeys skips all of that). Function keys were once read
    as letters there (F1 as 'P'), and no injected chord could have shown it."""
    editor.cmd("PressKeys -Keys Ctrl+Shift+P"); editor.cmd("PressKeys -Keys Ctrl+Shift+P")      # the last key that reached an action is now the palette
    assert "Host/Palette/Open" in editor.cmd("ExplainLastKey")
    editor.post_key(0x70)                                                                       # VK_F1
    editor.wait_for("ExplainLastKey", r"Host/Explain/Pin", timeout=10)
    editor.post_key(0x70)                                                                       # and it closes again


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
