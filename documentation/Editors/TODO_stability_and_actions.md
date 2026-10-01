# TODO - stability issues found while building the actions system (2026-10-01)

Found while testing the first slice of `actions_and_keybindings.md`. None was investigated to a root cause: they were parked on purpose.
The smoke suite (`source/Editors/LevelEditor/smoke`) now runs the **Debug** build and ends with an "editor problem report"; an assert fails the run.

## Open issues

| # | Issue | What is known | Where to start |
|---|---|---|---|
| 1 | **Vulkan validation error `VUID-vkCmdDrawIndexed-None-08600`** ("pipeline created with layout A statically uses descriptor set 0, not compatible with the currently bound layout B"; "the set push constant ranges is different"). It also pops the red Error modal. | About 1,000 per full Debug suite run; also present in the old Debug build from before the actions work (99 in its run), so **not caused by it**. Silent at idle (0 errors after 8 s). Per test file on Release only `test_resource_editors.py` produced any (2). | Find the draw that binds one pipeline layout and draws with another pipeline: an ImGui or preview draw while a resource editor is open (Material/Texture/GeomStatic preview). The harness report prints the message and count. |
| 2 | **Intermittent access violation (0xc0000005)** when the harness opens the **Material** resource editor (`test_resource_editors.py::test_open_resource_editor[Material]`; the next command finds the editor dead). | Only after earlier tests have run: it follows `test_entities.py`, `test_folders.py` or `test_read_only_queries.py`, and passes alone. Seen on Debug and Release, before and after the E10 rename. **Stack** (Debug trace log): `xeditor::mesh_preview::Draw` (`xeditor_mesh_preview.h:247`) -> `e19::mesh_manager::Rendering` (xGPU's `E19_mesh_manager.h:61`) -> `cmd_buffer::Draw` -> `vkCmdDrawIndexed` -> access violation reading 0x18 inside the Vulkan driver/layer. Same family as #1 (the draw is made with a pipeline/descriptor state that does not match). | Look at what `xeditor_mesh_preview` binds before `m_Meshes.Rendering(...)` when a preview is rebuilt or reused (`m_Instance`, `m_LightUBO`, the vertex/index buffers of a mesh that was recreated). |
| 3 | **An assert, hit once** in a Debug run (the user clicked Abort: "abort() has been called", exit code 3), during the `test_scenes_and_levels.py` stretch of a full run. | The text and stack were **lost**: the trace log is truncated at every launch. Not reproduced in 8 further Debug runs. | Asserts now go to `LevelEditor.problems.log` (append-only, with stack) and the harness exits instead of showing a dialog (`XEDITOR_NO_ASSERT_DIALOG`). If it recurs, the stack is in that file. |
| 4 | `Build/xLION.vs2022/LevelEditor.trace.log` is **1.1 GB**. The trace is never rotated or capped. | The Debug/Release copies are 6-12 MB. | Cap or rotate in `xeditor::diagnostics::Start`; find what writes it so verbosely. |
| 5 | `example.lionprj/Assets/imgui_level_editor.ini` is modified by every editor launch, including the smoke runs. | It is UI layout (per-user state living inside the project). | Same root as the open question in `actions_and_keybindings.md`: per-user state needs a per-user home. |

## Not done yet (actions / keybindings)

- `toolbar.imgui` still draws its own tooltip (it is an independent library; it needs a hook like the inspector's `m_OnHelp`), and xGPU's examples keep their own.
- Wrong help texts found while looking at property hints: the Texture editor's "UAdress Mode" (also spelled that way) says "Size in bytes of the file".

- **xproperty:** the inspector does not evaluate `member_override_check` (the "overridden" tint and revert button) for rows of a map or atomic array:
  they go through a separate leaf branch (`xPropertyImGuiInspector.cpp`, "Atomic array"). The Keymap page therefore draws its own "Reset" in the
  append hook. Fixing it in the inspector would give every list-of-values the prefab-style marker. Also: a map keyed by text now shows its key as the
  row label (done, `ElementLabel`).

- The Keymap page in Project Settings, the command palette, F1 pin/overlay, the status line.
- Binding the inspector's `m_OnHelp` and a hint delegate on `toolbar.imgui` (so every tooltip comes from one system).
- Keys on enum values (Q/W/E/R are four actions for now), `member_icon`.
- Save/Undo/Redo still call functions directly, not `xeditor::Run` commands.
- Other editors' keys still hand-written: xresource_editor files tab, Level tree F2/Delete, Texture (its Space overlaps the Drawer), Material graph, text widget, camera fly.
- The real keyboard path and the hover hint / menu look were only verified through `PressKeys` (shared resolver) and the build, not by hand in the UI.

## Naming (done 2026-10-01, and what is left)

Done: the asset browser / asset manager library formerly called "E10" is now `xresource_editor` (namespace `xresource_editor::`, files
`xresource_editor_*.h`, `assert_browser` -> `asset_browser`, the `AsserBrowser` member -> `AssetBrowser`); the plugin shaders `E21_*`, `E23_*`, `E28_*`
are `xgeom_static_*`, `xskeleton_*`, `xfont_*` (the `_frag/_vert/_geom` suffix is kept: the build picks the stage from it); the drag payload and popup ids
that said E29 say `LEVEL_...`; "(open from E29)" in five editors' messages now says "the editor".

Left on purpose:

- **Comments** that mention E19 / E27 / E29 (about 300): they describe where an idea came from. A sweep can rewrite them later.
- **xGPU's own `E10_TextureResourcePipeline` example** keeps its name (only its includes and `xresource_editor::` uses were updated).
- `xeditor_mesh_preview.h` and `xskeleton_editor_view.h` still include xGPU's example header `source/Examples/E19_MaterialEditor/E19_mesh_manager.h`
  (a library depending on an example). It should move into a library (`xeditor_tools` is the natural home) and the example include it from there.
- **xGPU `CMakeLists.txt`** lists `plugins/xgeom_static.plugin/.../E21_GridShader_{frag,vert}.glsl`, which no longer exist in the plugin (the grid shader moved to
  `xeditor_tools`): a stale entry that predates the rename.
- `CMakeLists.txt` keeps a one-time patch for an old `E19_TextEditor.h` path in `xmaterial.plugin` (compatibility with older checkouts).

## Housekeeping

- `actions.imgui` is committed locally on top of the official depot's first commit (`LIONant-depot/Actions.imgui`, LICENSE only) and
  fetched by `CMakeLists.txt` next to toolbar.imgui. **Not pushed yet** - `git push` from `dependencies/actions.imgui` publishes it; until then
  a fresh checkout would clone the empty depot.
- **Nothing is committed** in: xLION (this repo), `dependencies/xproperty`, `dependencies/xeditor`, `plugins/xlevel.plugin`.
  The four repos change together (xproperty: `member_dynamic_reason`, `m_OnHelp`, noexcept function members; xeditor: `host.h` drawer toggle,
  `diagnostics.h` problems log; xlevel.plugin: `session_actions`).
