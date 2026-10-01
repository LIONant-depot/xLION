# xLION Actions, Keybindings and Hints - design

> Status: **first slice built and tested** (2026-10-01) - see "Implementation status" below. The rest is design. Reference reading: *A 21st-Century Command and Keybinding System for
> Creative Editors* (taken as a strong reference, not a spec). Facts about today's code come from a survey of
> `xeditor`, `xundo`, `xcmdline`, `xproperty`, `xlevel.plugin`, `xscene.plugin`, xresource_editor and the resource-editor plugins.

## Implementation status (2026-10-01)

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
| **`Editor/Save|Undo|Redo|Compile`** for every resource editor (Ctrl+S, Ctrl+Z, Ctrl+Y, Ctrl+Shift+B): `document_actions` on `document_editor` (Material, Font, GeomStatic, GeomSkin, Skeleton, AnimPackage, PhysicsMaterial, MaterialInstance) and on the hand-written Texture editor | `xeditor_document_actions.h` |
| **`Assets/Rename|Cut|Copy|Paste|Delete`** (F2, Ctrl+X/C/V, Delete) while the drawer's Assets tab has the focus. The tab stops reading those keys itself when the host sets `m_bFileKeysByHost` (xGPU's examples keep the old behaviour) | `LevelEditor_FilesActions.h`, `xresource_editor_asset_browser*.h` |
| **Live key texts in menus and toolbars**: the shared editor toolbar (Undo / Redo / Save / Compile), the Level tree and the asset browser's context menus show the key the action really has (`xeditor::ShortcutText`, a host service); they keep their built-in text when the host provides none | `xeditor/shortcuts.h`, `xeditor_toolbar.h` |
| **F1 keyboard overlay**: the keys as a keyboard, coloured by what is on each (action / host-wide / both or other modifiers / nothing), a tooltip per key, Ctrl/Shift/Alt layers (held or ticked) - the idea from Unity's shortcut manager | `ximgui_actions_ui.h` (`DrawKeyboardOverlay`) |
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
- **Not built yet**: the status line with mouse gestures, the F1 *pinned hint card* (the keyboard overlay is built), binding the inspector's
  `m_OnHelp`, the toolbar.imgui tooltip delegate, keys on enum values (Q/W/E/R are four actions for now), moving Save/Undo/Redo onto
  `xeditor::Run` commands, the other editors' keys (xresource_editor files tab, tree F2/Delete, Texture, ...). Nothing is committed to the dependency
  repos yet, and `actions.imgui` has no remote: `CMakeLists.txt` can only fetch it (like toolbar.imgui) once it is published.

## 0. The rule this design follows: reuse, don't reinvent

There is no new language here. Each concept a keybinding system needs maps onto something the code base already
has. Where the existing system falls short, **that system grows**: it gets a new tag, a new delegate, or a wider
callback. A parallel mechanism is never added next to it. This exercises the existing code, keeps one concept per
idea, and pushes xproperty, xundo and xeditor to get better instead of getting company.

| Keybinding concept | Is already | Growth needed |
|---|---|---|
| An action | an xproperty **function member**: `obj_action<"Delete", &T::Delete>` (inspector already calls it via `TryCallFunction`) | none |
| Action identity / ID | its **property path**: `Level/Entity/Delete` | none |
| Grouping / categories | `obj_scope<"Entity", ...>` | none |
| Registry of all actions | the xproperty type registry (`XPROPERTY_DEF` / `XPROPERTY_REG`) | none |
| Help text | `member_help<"...">` | none |
| Hidden / disabled | `member_dynamic_flags<fn>` (`m_bDontShow`, read-only = disabled; xfont uses it everywhere) | **a reason string** next to the flags (section 2) |
| Default keys, icon | `member_user_data` tags (the existing extension point) | new tags `member_keys<"Ctrl+D">`, `member_icon<"...">` (no change to xproperty core) |
| Toggle / mode keys (Q/W/E/R) | a **bool or enum property** (`member_enum_value`) | `member_keys` on enum values |
| Listing actions (palette, keymap page, AI) | xproperty enumeration (`sprop::collector`, `ListProperties`) | none |
| Editing a document | `xundo` commands through `xeditor::Run / RunQuery / RunGroup` | none |
| Pipe / CLI addressing | `host::dispatch` with `Name\Command -Path ...`, like `SetProperty -Path` | `RunAction -Path`, `PressKeys -Keys` |
| Keymap file | an **xtextfile property file**, the same `"path" ;type value` rows as `Library.config.txt` | none |
| Keymap editor page | an **xproperty inspector** inside Project Settings (`m_ExtraPluginTabSections`) | a chord-capture widget via `member_custom_render_replace_value` |
| "Differs from default/preset", reset | the inspector's **override** UI (`m_OnOverrideCheck` / `m_OnOverrideReset`), the same one prefabs use | none |
| Tooltip subject | a **property reference** (object + path); assets and descriptors are xproperty objects too | the inspector's help goes through a delegate |
| Hooks between libraries | `xdelegate`, as the inspector's `m_On*` events already are | one delegate per library with tooltips |
| Key chord type and names | `ImGuiKeyChord`, `ImGui::GetKeyChordName` (ImGui 1.93) | none |
| Fuzzy search | `xstrtool::SubstringDamerauLevenshteinDistanceI`, the console's autocomplete ranking | the palette and the console share one list |

## 1. Why this is about Actions, not keys

Today every key, menu item, toolbar button and tooltip is hand-written, separately:

| Today | Consequence |
|---|---|
| ~20 `ImGui::IsKeyPressed` checks in 9+ files, calling functions or setting variables | There is no keymap to show, search or change. |
| `MenuItem("Save", "Ctrl+S")`: the shortcut text is a literal string | The text can disagree with the real key. |
| Toolbar buttons are labelled "W", "E", "R" by hand, separately from the key checks | The same kind of drift, in a second place. |
| `BeginDisabled(bCanSave)` in the UI, and a refusal string inside the command | Enabled state is decided twice, and disabled items never say why. |
| Save, Undo/Redo and Play call functions directly; everything else builds command strings | Two ways of doing the same thing. |
| Space toggles the Drawer **and** the Texture preview's light; Ctrl+S has no focus gate; `document_editor` editors have no Ctrl+S or Ctrl+Z | Conflicts nobody can see, and missing basics. |

A key is one way to reach an action. A menu item, a toolbar button, a context menu, the palette, the inspector button
and the pipe are other ways. All of them should be generated from one declaration, and that declaration already
exists: the xproperty description of an object.

```
  Keys  Menus  Toolbars  Context menus  Inspector button  Palette  Pipe (RunAction / PressKeys)
    \_____\______\_________\________________\_______________/___________/
                               |
          xproperty function members on the editor's objects    (path, help, dynamic flags, keys)
                               |   method body reads context (selection...) and builds command strings
                               v
          xeditor::Run / RunQuery / RunGroup  ->  xundo commands  ->  Document
```

**Why the keys don't go on the `xundo` commands themselves:**

- Commands are explicitly addressed (`DeleteEntity -Scene <hex> -Id <hex>`), but a key press is contextual ("delete
  whatever is selected here").
- One action can produce several commands, and several actions can share one command.
- Some actions are not document edits at all: Drawer, gizmo tool, camera framing, panel focus.

The commands stay unchanged, as the layer below the actions.

**The rule:** an action that edits a document does it through `xeditor::Run*`. That keeps every key press logged,
undoable, gated by the write lock, and visible to the AI.

## 2. Declaring actions: it is just xproperty

Each editor already is (or gets) an object, and that object describes its actions in its `XPROPERTY_DEF`:

```cpp
XPROPERTY_DEF("Level", xlevel::session
    , obj_scope<"Entity"
        , obj_action<"Delete",    &session::DeleteSelection
            , member_help<"Deletes the selected entities and their children">
            , member_keys<"Delete">
            , member_dynamic_flags<+[](const session& S, settings::context& C)
                { return S.HasSelection() ? flags::type{} : C.Disabled("nothing selected"); }>>
        , obj_action<"Duplicate", &session::DuplicateSelection, member_keys<"Ctrl+D">, ...>
        , obj_action<"Rename",    &session::RenameSelection,    member_keys<"F2">, ...>>
    , obj_scope<"Viewport"
        , obj_member<"Tool", &session::m_SceneTool          // an enum property: the toolbar draws it as radio buttons
            , member_enum_value<"Select", member_keys<"Q">>, member_enum_value<"Move", member_keys<"W">>
            , member_enum_value<"Rotate", member_keys<"E">>, member_enum_value<"Scale", member_keys<"R">>>
        , obj_action<"Frame", &session::FrameSelected, member_keys<"F">>>
    , obj_action<"Save", &session::Save, member_keys<"Ctrl+S", key_flags::IN_TEXT>>
)
```

The paths are `Level/Entity/Delete`, `Level/Viewport/Tool`, `Level/Save`: the same path language that
`SetProperty -Path` and the `*.config.txt` files already use.

- **Running an action** calls the function member, the same way the inspector already does when an `obj_action`
  button is clicked. `DeleteSelection` builds the command strings and calls `xeditor::RunGroup(m_Undo, ...)`.
- **A key on an enum value or a bool sets that property.** The Q/W/E/R gizmo tools stop being a special case: they
  are the `Tool` property. Pressing W sets it to Move, and the toolbar shows the same property as radio buttons.
  Any property can get a key this way; nothing extra is needed for it.
- **Growing `member_dynamic_flags`: the reason.** The callback already receives `settings::context&`. It grows a way
  to say *why* something is disabled or hidden (`C.Disabled("nothing selected")`, or a reason field next to the
  flags). Every existing xproperty user benefits from this: the inspector can show "read-only because …" on ordinary
  properties too. This replaces the duplicated `BeginDisabled` checks.
- **New tags, using the existing extension point:** `member_keys<"Ctrl+D">`, with optional `key_flags::IN_TEXT`, which
  lets the key fire while a text field has focus (Save, Palette). Also `member_icon<"...">`. Both are
  `member_user_data` structs, the documented way to add metadata to a member, so xproperty's core does not change.

## 3. Scopes are the path prefix plus the object that is live

There is no separate scope field. **The scope of an action is its path prefix**, and **which actions are live is
decided by which objects are live under the mouse or focus**:

```
  focused / hovered panel's object      e.g. Level/Viewport  (the session object, entered at the Viewport scope)
     -> its editor object               Level
     -> generic resource editor object  Editor   (Save / Undo / Redo / Compile for any resource_editor)
     -> host object                     Host     (Drawer, Palette, Explain, workspace Undo when the Drawer has focus)
```

- **How the chain is built.** Inside each panel's `ImGui::Begin`, the panel calls `xeditor::ActionScope(Obj, "Level/Viewport")`.
  This records the window → (xproperty object, path) mapping for the current frame.
- **How a key is resolved.** The host walks from `NavWindow` (the focused window) up through its parent windows.
  The hovered panel of the same editor is checked first, which keeps today's "Q/W/E/R work when hovering the viewport".
  The resolver runs once per frame, after all editors have drawn (outside any Begin/End, the same reason Play/Stop is
  deferred today):
  1. If `io.WantTextInput` is set, only `IN_TEXT` keys are considered.
  2. Walk the chain from the inside out. The first bound member that is visible and not disabled runs.
  3. If everything bound was disabled, nothing runs, and the innermost reason goes to the console log.
  4. The result is stored for `ExplainLastKey`.
- **Conflicts:**
  - The same chord twice under one prefix is a conflict, and the keymap page refuses it.
  - An inner prefix over an outer one is shadowing. It is allowed and shown.
  - Sibling paths (`Level/...` and `Texture/...`) never conflict.
- `IsOneOfMyWindowsFocused` / `g_pActiveLevelContext` are replaced by this mapping.

## 4. Discoverability: generated from the same declaration

Everything below reads the xproperty description. No string is written twice.

| Where | What the user sees |
|---|---|
| Menus, context menus | `xeditor::MenuItem(Obj, "Entity/Delete")` draws the label, the live key, the enabled state and the reason. It replaces the literal `"Ctrl+S"` strings. |
| Toolbars | `xeditor::ToolbarButton(Obj, "Viewport/Tool")` draws the icon, the toggled state (it is a property value) and the hint. |
| Inspector | Actions on an inspected object already appear as `obj_action` buttons. Once tagged, they show their keys. |
| Palette `Ctrl+Shift+P` | Fuzzy search over the members that are live in the current chain. Each row shows path, key and reason; Enter runs it. The command console's autocomplete uses the same list (it is broken today: nothing registers systems with `LevelEditorHistory` any more). |
| `F1`, explain | Pins the hint card for whatever is under the mouse (section 4b). Over empty space it shows a keyboard overlay of the panel's live keys plus its read-only gestures. |
| Change it where you see it | Right-click any menu item, button or inspector action → *Change shortcut…* |
| AI and smoke tests | `ListProperties`-style listing of the action members (path, keys, enabled or reason), plus `Name\RunAction -Path Entity/Delete` and `Name\PressKeys -Keys "Ctrl+D"`. The latter resolves exactly like a real key press and replies with what ran, or why nothing did. Also `ExplainLastKey`. Synthetic OS keyboard input has been unreliable in this project; `PressKeys` lets the smoke suite test every binding. |

**Space** stays the Drawer key. The Drawer becomes `Host/Drawer/Toggle` with `member_keys<"Space">`: an ordinary
bound action and the first hard-coded key to be converted.

## 4b. Hints: the tooltip, taken further, through one hook per library

The tooltip is the discovery tool people already use, so it becomes the backbone. **A hint's subject is a property
reference (object + path).** Actions are properties, so are inspector rows, and so are asset descriptors (they are
xproperty objects). That is one kind of subject, plus a plain-text fallback for one-off items.

What a card can say about its subject, all read from xproperty:

- path, `member_help`, live keys
- the disabled reason, from the grown `member_dynamic_flags`
- override state ("overridden, base = 3.0"), from the inspector's existing override check
- the **equivalent command**: `SetProperty -Path …` for data, the `Run:` line for actions. Hovering therefore teaches
  the console/CLI language.

There are three levels of detail:

1. **Hover**: one line, e.g. `Duplicate  Ctrl+D`, or `Duplicate - nothing selected`.
2. **Keep hovering, or hold `Alt`**: the full card.
3. **`F1`**: pins the card under the mouse, with *Change shortcut… / Copy command / Show in keymap / Reset override*.

A **status line** in each host window shows level 1 for whatever is under the mouse, plus that surface's gestures:
`Viewport · LMB select · Shift+LMB add · RMB fly · F frame`. When an action with a key is used from the mouse, the line
also shows `Tip: Ctrl+D` (quiet, never a popup).

**The hook contract.** A library keeps its current tooltip as the default, so it still works on its own. It exposes
one `xdelegate` that receives *what* is hovered, never pre-formatted text. Binding that delegate replaces the
default; there is no separate on/off flag. At startup the host binds `xeditor::Hint` in every library.

| Library | Today | Hook |
|---|---|---|
| xproperty inspector | Every label hover goes through `inspector::Help(const entry&)` (`xPropertyImGuiInspector.cpp:4199`). Enum-value help and truncated-string tooltips are separate (`:1275`, `:629`…). | `m_OnHelp(inspector&, const entry&, help_kind)`, next to the existing `m_On*` delegates. When it is bound, all of these call it instead of drawing. |
| toolbar.imgui | Its own `BeginTooltip` (`ximgui_toolbar.h:333`) | the same: one delegate on `toolbar_host_state` |
| xeditor `MenuItem` / `ToolbarButton`, `xeditor_toolbar.h` | hand-written `SetTooltip` | call `xeditor::Hint` directly |
| xresource_editor, plugin panels | ~30 ad-hoc `SetTooltip` | `xeditor::Hint(subject)`, or the text fallback |

## 5. Customising: per-user, shareable, in Project Settings

**The files are ordinary xtextfile property files** in the project's settings directory. They have the same shape as
`Library.config.txt`: the property path is the name, and the chord is the value.

```
example.lionprj/Project.config/Keymaps/
    <user>.keymap.txt          one per person (OS user name)
    <name>.keymap.txt          a named preset someone saved to share

[ xProperties : 3 ]
{ Name:s                        Value:?  }
  "Keymap/Base"                 ;string  "Unreal-like"
  "Level/Entity/Duplicate"      ;string  "Ctrl+Shift+D"
  "Level/Viewport/Frame"        ;string  ""                 // "" = unbound
```

- **Layers:** `member_keys` defaults (in code) → the base preset → the user's own file. Each file holds only the rows
  that differ from the layer below it. A path listed in a layer replaces all of that member's keys from the layers
  below.
- **Sharing:** any file in `Keymaps/` can be chosen as a base, including other people's personal files. A user only
  ever writes their own file; *Save as preset…* writes a new one.
- **Unknown paths are kept.** A preset made with a plugin you don't have loaded survives a round trip.
- **Moving later:** when per-user settings get a home outside the project, only the user's file moves.

**The page** is an **xproperty inspector** in Project Settings (`m_ExtraPluginTabSections`, the same way *Scripting*
is added):

- The tree is the action paths, so the scopes appear as `obj_scope` groups. A new plugin's editor appears without
  extra work.
- The value column is the chord. It uses a capture widget (`member_custom_render_replace_value`) that shows
  conflicts and shadowing as soon as a key is pressed.
- **"Changed from base" is shown and reset with the inspector's existing override UI** (`m_OnOverrideCheck` /
  `m_OnOverrideReset`). Layered keymaps are the same concept as a prefab instance overriding its prefab, so they use
  the same visuals.
- *Find by key*: press a chord to filter the tree to whatever uses it.
- Edits apply live and save to the user's file. They are preferences, not documents, so they don't go through undo
  (the same as the Scripting section).

## 5b. Customizable toolbars: the same layers, the same actions

A toolbar is an ordered list of action paths. Because a button is generated from an action, a user-defined toolbar needs no new
mechanism: it is one more thing the keymap layers carry.

```
"Toolbars[0]/Name"        ;string  "Scene"
"Toolbars[0]/Items[0]"    ;string  "Level/Viewport/ToolMove"
"Toolbars[0]/Items[1]"    ;string  "Level/Viewport/ToolRotate"
"Toolbars[0]/Items[2]"    ;string  "-"                           // separator
"Toolbars[0]/Items[3]"    ;string  "Level/Save"
```

- A toolbar listed in a layer replaces the same toolbar from the layer below (defaults < base preset < the user's file), so "my keys and my
  toolbar" travel together as one preset.
- The toolbar's owner asks first: `if (Ctx.DrawToolbar(Name, bVertical)) return;` - when there is a layout it is drawn (each item is a
  button with the live key as its hint, disabled with the reason when it cannot run), otherwise the owner draws its built-in one as before.
  The Level editor's "Editor" and "Scene" toolbars do this today.
- Layout and placement stay with `toolbar.imgui` (edge, docking, floating); the *contents* come from the layers. Items whose action is not
  live (another editor's, an unloaded plugin) are skipped, and the path is kept in the file.
- **Editing** (not built): drag an action from the keymap page or the palette onto a toolbar, drag buttons to reorder or off to remove,
  right-click a button -> *Change shortcut...* / *Remove from toolbar*. Both are edits of the user's layer, so *Reset* is the inspector's
  override reset.

## 6. Default keymap (one documented default; presets change bindings, never behaviour)

| Path | Keys |
|---|---|
| `Host/...` | `Space` Drawer · `Ctrl+Shift+P` Palette · `F1` Explain · hold `Alt` full hint |
| `Editor/...` | `Ctrl+S` Save (works in text) · `Ctrl+Z` Undo · `Ctrl+Y` / `Ctrl+Shift+Z` Redo |
| `Level/...` | `Delete` · `Ctrl+D` Duplicate · `F2` Rename · `Ctrl+X/C/V` · `Ctrl+A` · `Esc` Clear selection · `F5` Play · `Shift+F5` Stop |
| `Level/Viewport/...` | `Q W E R` = values of `Tool` · `F` Frame selected · inside a tool: `W E R` mode, `Esc` done |
| `Host/Assets/...` | `F2` · `Delete` · `Ctrl+X/C/V` · `Ctrl+A` (the xresource_editor keys, unchanged) |

What this brings with it:

- `document_editor` editors (Texture, Material, ...) get Ctrl+S and Ctrl+Z for the first time, through `Editor/...`.
- `Ctrl+Z` undoes the focused editor's history, or the workspace's when the Drawer has focus. That settles today's
  workspace-vs-Level Undo duplication.

## 7. Out of scope for now

| From the reference | Decision |
|---|---|
| Hold/tap/drag recognisers, clutches (RMB fly, Ctrl snap) | Stay in the tools; listed read-only on the page, in the overlay and in the status line. |
| Multi-stroke prefix chords, mnemonic families, radial menus | The palette covers the long tail. |
| Macros / repeat-last | Nearly free later: commands are strings and the console log already records them. |
| A predicate/`when` language | Not needed: path prefix + live object + `member_dynamic_flags`. |
| Team/org layers | Shared files plus a chosen base are enough. |
| Text widget keys, rename edit-box Esc | Text editing, not actions. |

## 8. Packaging: its own small depot

The actions, keys and hints system lives in **its own depot**, following the precedent of `toolbar.imgui`: a small
ImGui library that xeditor uses but that does not know about xeditor. Any ImGui tool that describes its objects with
xproperty can then get keys, menus, a palette and hints without pulling in the editor framework.

Working name: **`actions.imgui`** (namespace `ximgui::actions`, mirroring `ximgui::toolbar`).

| Lives in | What | Depends on |
|---|---|---|
| **xproperty** (grows) | the disabled/hidden reason on `member_dynamic_flags`; the inspector's `m_OnHelp` delegate | (as today) |
| **`actions.imgui`** (new depot) | `member_keys` / `member_icon` / `key_flags` tags (`member_user_data`: they don't need to be in xproperty); the scope map (`ActionScope`: window → object + path) and the per-frame resolver; `MenuItem` / `ToolbarButton`; the hint card (3 levels, F1 pin, status line); the palette; keymap layers load/save; the inspector-based keymap page | imgui, xproperty (+ its inspector and sprop/xtextfile serializer), xstrtool (fuzzy search) |
| **xeditor** (thin adapter) | the `Host/...` and `Editor/...` objects; binding the hint delegates in xproperty, toolbar.imgui and xresource_editor at startup; the `RunAction` / `PressKeys` / `ExplainLastKey` commands; registering the keymap page in Project Settings; the `Project.config/Keymaps/` location | `actions.imgui`, xundo, everything it uses today |
| **plugins** | `obj_action` / `member_keys` in their own `XPROPERTY_DEF`s | nothing new beyond the tag header |

The boundary stays clean through two rules:

- **`actions.imgui` never sees xundo or commands.** An action is a function member; what the function does is the
  owner's business. In xLION that means `xeditor::Run*`.
- **The hint card is built by whoever contributes to it.** `m_OnCardSection` is an `xdelegate`, and every listener
  can add a section. A tool with no listeners just gets the basics from xproperty.
  - the xeditor adapter adds `SetProperty -Path …` / `Run: …`
  - source control adds the lock state
  - the prefab system adds the override state

Also: toolbar.imgui does **not** depend on `actions.imgui`. It keeps its own tooltip delegate, and xeditor binds it.
Neither of the two small libraries needs the other.

## 8b. Composition patterns (the rules that make it plug into everything)

Composability is the point of this design, so these patterns are explicit and are checked in review. Each one is
already proven somewhere in the code base; none is new.

| # | Pattern | Here | Already proven by |
|---|---|---|---|
| 1 | **Depend on the description, not on the system.** A library reads xproperty descriptions and never includes the code that owns the objects. | `actions.imgui` knows xproperty, not xeditor, xundo, xlevel or plugins. | The inspector edits any object without knowing its owner. |
| 2 | **Extend by tags that don't know about each other.** Each library defines its own `member_user_data` tags. Tags from different libraries sit on one member side by side, and duplicates fail at compile time. | `member_keys` (actions.imgui) + `member_help` (xproperty) + override hooks (xscene) on the same member | xproperty's own UI tags (`member_ui`, `member_flags`, …) |
| 3 | **Cross boundaries with multicast delegates, never with calls up the stack.** A library raises an `xdelegate`; whoever cares listens; zero listeners is a valid state. | hint-card sections, `m_OnHelp`, the toolbar tooltip delegate | the inspector's `m_On*` events |
| 4 | **The default works alone; a listener replaces it.** No on/off flags. | the inspector's own help popup, toolbar.imgui's tooltip | toolbar.imgui and xproperty demos run standalone |
| 5 | **Pass the subject, not the rendering.** Delegates receive *what* (object + path), never pre-formatted text, so any number of listeners can add to it. | hint subjects, `ExplainLastKey` | `m_OnChangeEvent` passes path + values, not a message |
| 6 | **One identity everywhere: the property path.** Anything addressed by path composes with everything else addressed by path, with no glue code. | the keymap file, the pipe (`RunAction -Path`), the palette, hints and `SetProperty` all share `Level/Entity/Delete` | `*.config.txt`, `SetProperty -Path`, `ListProperties` |
| 7 | **Compose by nesting, never by ordering.** Scopes nest (path prefix plus window parent chain); the innermost wins. Registration order and plugin load order never change a result. | the key resolver, conflict detection | ImGui window and parent routing, `obj_scope` |
| 8 | **Compose by layered override.** Any number of layers, each holding only the differences, read with one rule. | code defaults → preset → user | prefab → instance overrides, with the same inspector UI |
| 9 | **Immediate mode: re-declare every frame, cache nothing.** Live objects are recorded during the frame and forgotten after it. Nothing needs unregistering, and a hot-reloaded Game.dll or a closed editor cannot leave a dangling pointer. | `ActionScope(Obj, Path)` | ImGui itself; the rule in `services_and_ui.md` that consumers re-`get` services after a reload |
| 10 | **No hidden globals in a library.** State lives in an object its owner holds, so two hosts, a test, or a headless run can coexist. | `ximgui::actions::context`, held by the host | `toolbar_host_state`; `host::current()` is the *one* global, and it lives in xeditor |
| 11 | **Edits stay on the edit path.** Composition never creates a second way to mutate. An action is a function; if it edits a document, it goes through `xeditor::Run*`. | every document-changing action | `xeditor::Run / RunGroup` |

**Smells this rules out (check for them in review):**

- a library including its consumer;
- a single-slot callback where several systems could reasonably want in;
- a string formatted for display crossing a boundary;
- a result that depends on registration order;
- a pointer to an object kept across frames;
- a second ID scheme next to property paths.

**One known weakness of pattern 6:** paths are names, so renaming a member orphans its keymap rows. The `*.config.txt`
files have the same weakness. Keymap files keep unknown paths instead of dropping them, so nothing is lost; a rename
needs a one-line migration. If renames become common, the fix belongs in xproperty (for example, member aliases), so
that config files benefit too, not only keymaps.

## 9. Phases (each builds and behaves at least as well as before)

1. **xproperty grows:**
   - the reason on `member_dynamic_flags`;
   - `m_OnHelp` on the inspector.

   These are useful on their own; the inspector can show "read-only because …" immediately.
2. **`actions.imgui` depot:**
   - the tags, `ActionScope`, the resolver, `MenuItem` / `ToolbarButton`;
   - a tiny standalone demo, the way toolbar.imgui has one.
3. **xeditor adapter:**
   - the `Host/...` and `Editor/...` objects;
   - `RunAction` / `PressKeys` / `ExplainLastKey`.

   Declare the first actions in the session `XPROPERTY_DEF`s and migrate the keys:
   - Drawer Space; Save/Undo/Redo (they stop bypassing commands);
   - Q/W/E/R/F; tree F2/Delete;
   - the xresource_editor keys; Texture Space (moved to `Texture/Preview`, so it no longer fights the Drawer).

   Add smoke tests that drive keys through `PressKeys`.
4. **Find:** in `actions.imgui`, the hint card, the status line, the palette and F1. In xeditor, binding the delegates,
   and the console autocomplete sharing the palette's list.
5. **Change:** in `actions.imgui`, the keymap layers and the inspector-based page. In xeditor, the `Keymaps/`
   location, the Project Settings entry, *Change shortcut…* and presets.

## 10. Open questions

- **Depot name:** `actions.imgui` is a working name (the owner's call).

- **Which object carries the generic `Editor/...` actions** (Save/Undo/Redo/Compile)? `resource_editor` (the base)
  is the likely home, because `xlevel::session` does not use the `document_editor` template.
- **How should `member_dynamic_flags` carry the reason?** Either through the existing `settings::context&` argument,
  or by returning a small struct that holds the flags plus a reason. Pick whichever keeps xfont's existing callbacks
  compiling.
- **Per-user UI state:** the ImGui ini (`Assets/imgui_level_editor.ini`) is per-user state that lives inside the
  project. It belongs wherever per-user settings eventually go.
