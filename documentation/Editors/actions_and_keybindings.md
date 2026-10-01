# xLION Actions, Keybindings and Hints - design

> Status: **phases 1-5 built and tested** (2026-10-02) - see "Implementation status" below; what is left is listed at its end and in `TODO_stability_and_actions.md`. Reference reading: *A 21st-Century Command and Keybinding System for
> Creative Editors* (taken as a strong reference, not a spec). Facts about today's code come from a survey of
> `xeditor`, `xundo`, `xcmdline`, `xproperty`, `xlevel.plugin`, `xscene.plugin`, xresource_editor and the resource-editor plugins.

## Implementation status (2026-10-02)

Built, compiled in Release, and covered by `smoke/test_actions.py` (the whole smoke suite passes):

| Piece | Where |
|---|---|
| `member_dynamic_reason` tag (why a property/action is unavailable; the inspector shows it read-only with the reason in its help) | xproperty `my_property_ui.h` |
| `m_OnHelp` delegate (a listener may replace the inspector's built-in help card) | xproperty `xPropertyImGuiInspector.h/.cpp` |
| `noexcept` (and `const noexcept`) member functions as reflected actions | xproperty `xproperty.h` |
| `actions.imgui` depot: `member_keys` tag, chords, scopes, key resolution, `MenuItem`/`ToolbarButton`/`Button`, `DrawToolbar`, hint line + Alt card, keymap + toolbar layout files with layers | `dependencies/actions.imgui/` |
| Level editor actions: `Level/Save`, `Undo`, `Redo` and `Level/Viewport/ToolSelect|Move|Rotate|Scale` (the hand-written Ctrl+S/Z/Y and Q/W/E/R checks are gone); its File>Save and Save/Undo/Redo/Q/W/E/R toolbar buttons show the live key and why-not | `xlevel_session.h` |
| Host action `Host/Drawer/Toggle` (Space) - the drawer key is now an ordinary rebindable action | `LevelEditor_App.h`, `xeditor/host.h` |
| Pipe: `ListActions`, `RunAction -Path`, `PressKeys -Keys`, `ExplainLastKey` | `LevelEditor_Commands_Actions.h` |
| **Command palette** (`Ctrl+Shift+P`, works inside text fields): search over what is live where you were working, Enter runs it, unavailable ones greyed with the reason | `ximgui_actions_ui.h`, `Host/Palette/Open` |
| **Keymap page** in Project Settings ("Keymap"): an xproperty inspector over a reflected `std::map` (one row per action, key = action path, value = keys); typed edits, a "Set key" capture button and a "Reset" button per changed row; styled with the Project Settings tab's own inspector settings; edits are saved to your own keymap file | `ximgui_actions_ui.h` (`keymap_page`) |
| xproperty: a text-keyed map shows its key as the row label | `xPropertyImGuiInspector.cpp` (`ElementLabel`) |
| Pipe: `BindKey -Path -Keys` / `ResetKey -Path` (edit your keymap file), `ActionProblems` | `LevelEditor_Commands_Actions.h` |
| **More Level actions**: `Level/Play` (F5), `Level/Stop` (Shift+F5), `Level/Entity/Delete` (Delete), `Level/Entity/Rename` (F2; the tree takes the request) | `xlevel_session.h`, `xlevel_panel_level_tree.h` |
| **`Editor/Save|Undo|Redo|Compile`** for every resource editor (Ctrl+S, Ctrl+Z, Ctrl+Y, F5 builds, F6 feedback): `document_actions` on `document_editor` (Material, Font, GeomStatic, GeomSkin, Skeleton, AnimPackage, PhysicsMaterial, MaterialInstance) and on the hand-written Texture editor | `xeditor_document_actions.h` |
| **`Assets/Rename|Cut|Copy|Paste|Delete`** (F2, Ctrl+X/C/V, Delete) while the drawer's Assets tab has the focus. The tab stops reading those keys itself when the host sets `m_bFileKeysByHost` (xGPU's examples keep the old behaviour) | `LevelEditor_FilesActions.h`, `xresource_editor_asset_browser*.h` |
| **Live key texts in menus and toolbars**: the shared editor toolbar (Undo / Redo / Save / Compile), the Level tree and the asset browser's context menus show the key the action really has (`xeditor::ShortcutText`, a host service); they keep their built-in text when the host provides none | `xeditor/shortcuts.h`, `xeditor_toolbar.h` |
| **The keyboard** (`Shift+F1`, and under the palette): one widget drawn as keycaps - Ctrl / Shift / Alt are keys on it (click or hold to see that layer), each key shows its action's name, colours say action / host-wide / both, a corner mark says "more with other modifiers", a gold ring follows the palette's selected row. A details strip says what is on the hovered key; a click keeps it. The idea from Unity's shortcut manager | `ximgui_actions_ui.h` (`DrawKeyboard`, `DrawKeyboardOverlay`) |
| **The mouse beside the keyboard**: LMB / RMB / wheel coloured the same way, from the **gestures** each surface declares (`Ctx.Gestures("Viewport", table)`: descriptions of what the mouse does; the Level viewport and tree, and the 3D previews of Static Geom, Skin Geom, Skeleton, Anim Package and Texture declare theirs). Pipe: `ListGestures` | `ximgui_actions.h` (`gesture`), `xlevel_session.h`, `xeditor_document_actions.h` (`PreviewGestures`) |
| **Status line**: a quiet strip at the bottom of the window listing the gestures of the surface under the mouse (the layer of the modifiers held) | `ximgui_actions_ui.h` (`DrawStatusLine`) |
| **`F1` explains** (`Host/Explain/Pin`): over something that has a hint it pins the hint card with *Change shortcut...* (capture in place), *Reset*, *Copy command*, *Show in keymap* (the drawer opens on Project Settings at the Keymap section) and *Keyboard*; over nothing it shows the keyboard | `ximgui_actions_ui.h` (`DrawPinnedCard`), `LevelEditor_FilesActions.h` |
| **Key clashes**: capturing a key another action of the same scope has asks *Replace / Cancel* (on the Keymap page and on the pinned card); `BindKey` says it in its reply | `ximgui_actions.h` (`PollCapture`, `FindClash`, `ResolveClash`) |
| **Presets**: the Keymap page has *Based on* (any keymap file of the project) and *Save my keys as it* (writes your changed keys and toolbars as a keymap others can sit on). Pipe: `ListKeymaps`, `UseKeymap -Name`, `SaveKeymapAs -Name` | `ximgui_actions_keymap.h`, `ximgui_actions_ui.h` |
| **Keymap page grouped by editor**: one collapsible section per editor (the first part of the action path) | `ximgui_actions_ui.h` (`keymap_page`) |
| **Console suggestions**: the command console offers the workspace's commands, every open session's (`Name\Command`) and the live actions (`RunAction -Path ...`, the palette's list); before, it offered nothing | `xeditor/host.h` (`routable_commands`), `LevelEditor_Panel_CommandConsole.h` |
| **Hint delegates in every library**: `toolbar.imgui` has `m_OnTooltip` (the Level binds the editors' hint window); the Project Settings inspector is bound like every other | `ximgui_toolbar.h`, `LevelEditor_FilesActions.h` |
| **Selecting an entity turns the Level camera to it**: the eye stays, the rotation glides (0.3 s, smootherstep) | `xlevel_session.h` |
| The hovered window only counts for the editor that has the focus (a Delete aimed at the asset browser can never reach an entity under the mouse) | `ximgui_actions.h` (`FocusOrder`) |
| **Build is `F5`, Feedback is `F6`** in every resource editor (`Editor/Compile`, `Editor/Feedback`; the Feedback action opens the toolbar's Feedback popup). In the Level editor `F5` is Play and `Shift+F5` Stop: different editor, no clash | `xeditor_document_actions.h`, `xeditor_toolbar.h` |
| **The Level editor's top bar is the shared one**: Undo / Redo / Save on the left, Play + Step in the middle (where the others have Compile + Feedback). No File menu and no separate Editor toolbar row (they were Save / Undo / Redo / Assets / Play / Step / Hierarchy / Inspector / Systems); the Scene toolbar (Q W E R F, Pivot, Local) stays in the viewport | `xlevel_session.h` (`RenderParentEditorToolbar`), `xeditor_toolbar.h` |
| **Each editor's own keys** (the ones it used to read itself): `Texture/Preview/LightFollowsCamera` (L; was Space), `AnimPackage/Preview/PlayPause` (P; was Space), `GeomStatic/Preview/LightFollowsCamera` (F). Space now only means the drawer. `document_editor::RegisterActions` lets an editor make its own actions live in its windows | `xtexture_editor.h`, `xanim_package_editor.h`, `xgeom_static_editor.h` |
| **`xeditor::hint`** - THE hint window: topic, body, the shortcut as a key cap, why-unavailable, small print; always fully on screen (placed like the inspector's help: beside the cursor, on the side with room, on the cursor's monitor). Used by action hints, the Play/Stop transport, the shared toolbar, every former `SetTooltip` (38 calls, `xeditor::hint::Text`), and hand-built tooltip windows are kept on screen too | `xeditor/hint.h` |
| Inspector property help is the same hint: `m_OnHelp` now carries a ready `help_info`; `xeditor::BindInspectorHints` shows name / help / unavailable reason / type and path | `xPropertyImGuiInspector.h`, `xeditor_inspector.h` |
| Every type that declares actions registers itself (`XIMGUI_ACTIONS_OWNER`), so the Keymap page, menus and `BindKey` know every editor's keys from the start, with nothing open | `ximgui_actions.h` |
| Keymap files loaded at startup from `Project.config/Keymaps/<user>.keymap.txt` (+ base preset chain) | `LevelEditor_AppInit.h` |

Differences from the design above that building it settled:

- **Owners are default-constructible**: xproperty creates objects by default construction, so an action owner (`session_actions`,
  `host_actions`) holds a pointer to what it acts on, not a reference.
- **Scopes are listed by the panel**, not derived: `Scope(Owner, "Viewport", ...)` / `ScopeWindow(window, Owner, ...)` /
  `Global(Owner, "Drawer")` name the sub-scopes (`obj_scope`) that window makes live; the object's root actions are always live.
  Innermost first: focused window chain, then hovered window chain, then the host's.
- **Frame protocol**: `NewFrame()` (after ImGui::NewFrame: run what menus chose, resolve keys) ... panels register their scopes ... `EndFrame()`.
  Keys, and the pipe between frames, resolve against the last completed frame.
- **Behaviour changes, deliberate**: Ctrl+S now needs one of the Level's windows to be focused (it used to fire whenever the editor was
  visible); Undo/Redo buttons are disabled when there is nothing to undo/redo (they were only disabled while playing).
- **Not built yet** (see the TODO file for the reasoning):
  - the **toolbar editing UI**: layouts load from the keymap files, but the Level's Scene toolbar still has items that are not actions
    (Frame, Pivot, Local), so there is nothing complete to edit;
  - **keys on enum values** (Q/W/E/R are four actions: clear and discoverable, so left alone) and `member_icon`;
  - Save / Undo / Redo as `xeditor::Run` commands: they are not undo steps themselves, and Save is a query, so they stay direct calls;
  - gestures for the Material / Font previews and the asset browser;
  - the "Tip: Ctrl+D" suggestion in the status line when an action with a key is used from the mouse.
