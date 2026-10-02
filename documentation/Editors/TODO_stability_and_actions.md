# TODO - stability issues found while building the actions system (2026-10-01)

Found while testing the first slice of `actions_and_keybindings.md`. None was investigated to a root cause: they were parked on purpose.
The smoke suite (`source/Editors/LevelEditor/smoke`) now runs the **Debug** build and ends with an "editor problem report"; an assert fails the run.

## Open issues

| # | Issue | What is known | Where to start |
|---|---|---|---|
| 1 | **Vulkan validation error `VUID-vkCmdDrawIndexed-None-08600`** ("pipeline created with layout A statically uses descriptor set 0, not compatible with the currently bound layout B"; "the set push constant ranges is different"). It also pops the red Error modal. | About 1,000 per full Debug suite run; also present in the old Debug build from before the actions work (99 in its run), so **not caused by it**. Silent at idle (0 errors after 8 s). Per test file on Release only `test_resource_editors.py` produced any (2). | Find the draw that binds one pipeline layout and draws with another pipeline: an ImGui or preview draw while a resource editor is open (Material/Texture/GeomStatic preview). The harness report prints the message and count. | **Fixed 2026-10-02 (probable cause).** xGPU cached the pipeline for a draw by the ADDRESS of the pipeline instance and by `renderpass ^ pipeline address`; when a preview is rebuilt, the next pipeline/instance can land at the address of a destroyed one and was handed its cached `VkPipeline` (a layout that does not match the descriptor sets just bound: this error, and a dangling pointer: #2). Both caches are now keyed by a unique serial and an entry is only trusted for the render pass it was made for (`xgpu_vulkan_window.cpp` setPipelineInstance). Evidence: 0 errors in 5 repeats of the resource-editor + action tests and in a full run; it showed once in an earlier full run. The harness now fails the run on any Vulkan validation error, so a return is caught. |
| 2 | **Intermittent access violation (0xc0000005)** when the harness opens the **Material** resource editor (`test_resource_editors.py::test_open_resource_editor[Material]`; the next command finds the editor dead). | Only after earlier tests have run: it follows `test_entities.py`, `test_folders.py` or `test_read_only_queries.py`, and passes alone. Seen on Debug and Release, before and after the E10 rename. **Stack** (Debug trace log): `xeditor::mesh_preview::Draw` (`xeditor_mesh_preview.h:247`) -> `e19::mesh_manager::Rendering` (xGPU's `E19_mesh_manager.h:61`) -> `cmd_buffer::Draw` -> `vkCmdDrawIndexed` -> access violation reading 0x18 inside the Vulkan driver/layer. Same family as #1 (the draw is made with a pipeline/descriptor state that does not match). | Look at what `xeditor_mesh_preview` binds before `m_Meshes.Rendering(...)` when a preview is rebuilt or reused (`m_Instance`, `m_LightUBO`, the vertex/index buffers of a mesh that was recreated). | Same cause as #1 (see there): the draw went through a cached pipeline of a destroyed pipeline instance. The four `xfail` marks that name this item now pass (XPASS). |
| 3 | **An assert, hit once** in a Debug run (the user clicked Abort: "abort() has been called", exit code 3), during the `test_scenes_and_levels.py` stretch of a full run. | The text and stack were **lost**: the trace log is truncated at every launch. Not reproduced in 8 further Debug runs. | Asserts now go to `LevelEditor.problems.log` (append-only, with stack) and the harness exits instead of showing a dialog (`XEDITOR_NO_ASSERT_DIALOG`). If it recurs, the stack is in that file. |
| 4 | `Build/xLION.vs2022/LevelEditor.trace.log` is **1.1 GB**. The trace is never rotated or capped. | The Debug/Release copies are 6-12 MB. | Cap or rotate in `xeditor::diagnostics::Start`; find what writes it so verbosely. |
| 5 | `example.lionprj/Assets/imgui_level_editor.ini` is modified by every editor launch, including the smoke runs. | It is UI layout (per-user state living inside the project). | Same root as the open question in `actions_and_keybindings.md`: per-user state needs a per-user home. |

## Not done yet (actions / keybindings)

Everything in phases 1-5 of `actions_and_keybindings.md` is built (2026-10-02). What is left, and why it was not done:

- **Toolbar editing UI.** Layouts load from the keymap files (`Toolbars` in a keymap), but the Level's Scene toolbar still has items that are not actions
  (Frame, Pivot, Local), so there is no complete default layout to edit. Make those three actions first (and give Frame its key), then a layout editor
  is a list of action paths with a picker.
- **Keys on enum values** (`Viewport/Tool` as one property with a key per value) and `member_icon`: Q/W/E/R are four actions today, which is clear and
  discoverable, so it was left.
- **Save / Undo / Redo as `xeditor::Run` commands**: Undo and Redo are not undo steps themselves and Save is a query, so there is nothing to record. They stay direct calls.
- **Gestures** are declared for the Level viewport and tree and for the 3D previews of Static Geom, Skin Geom, Skeleton, Anim Package and Texture. Not yet: the
  Material and Material Instance previews (mesh_preview), Font, the asset browser (double-click opens, drag onto a Level), the Material node graph.
- The status line does not yet show the "Tip: Ctrl+D" suggestion when an action with a key is used from the mouse.
- xGPU's examples keep their own tooltips.
- **The real keyboard path** is covered for function keys by `test_a_real_function_key_reaches_its_action` (WM_KEYDOWN posted to the window). Other keys, the
  mouse, and how the keyboard/mouse view and the pinned card look were only verified by building and by the pipe, not by hand.
- **Other editors' keys still hand-written**: the Material graph, the text widget, the camera fly keys (W A S D Q E while the right button is held).
- **project_guard** warns that a run changed `Project.config/Keymaps/user.keymap.txt` (it holds the drawer binding written at startup and is not in the snapshot).

- **xproperty:** the inspector does not evaluate `member_override_check` (the "overridden" tint and revert button) for rows of a map or atomic array:
  they go through a separate leaf branch (`xPropertyImGuiInspector.cpp`, "Atomic array"). The Keymap page therefore draws its own "Reset" in the
  append hook. Fixing it in the inspector would give every list-of-values the prefab-style marker.

- **xcontainer `unordered_lockless_map`** (found and fixed 2026-10-02): reading a map again from inside one of its own read callbacks (a recursive walk, a
  lookup of a child while holding the parent) is legitimate, but it deadlocked as soon as another thread was queued to write the map: the global lock stops
  admitting readers while a writer waits, and the writer waits for this thread's own outer read. Fixed in the map: a thread remembers the maps whose read lock
  it already holds (`details::read_holds`), a nested read just counts, and growing the map from inside a read of itself is left to the next call that is not
  nested. Two call sites in `xresource_editor_asset_mgr.h` (and ListAssets, the Resources tree) were also restructured earlier; they are harmless now.
  Still unsafe, and asserted in debug: needing the WHOLE map (resize / clear) while this thread is reading it.

- **Lost windows** (found and fixed 2026-10-02): the xGPU ImGui backend registered ONE invented 10000x10000 "monitor" around the origin, so ImGui never kept a
  window on a real display, and a modal ("Keep Play Mode Changes?") remembered at a position of another monitor layout opened in its own OS window out of
  reach, with the input focus. Now the backend registers the real monitors (`UpdateMonitors`, refreshed every frame) and every modal popup has
  `NoSavedSettings`. DPI scale is still 1.0 for every monitor.

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

- Everything above is committed and pushed in the dependency and plugin repos (xproperty, actions.imgui, xeditor, xresource_pipeline_v2, xGPU, toolbar.imgui,
  the plugins) and in xLION. `actions.imgui` is the official depot (`LIONant-depot/Actions.imgui`), fetched by `CMakeLists.txt` next to toolbar.imgui.
