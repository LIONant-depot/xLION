# TODO - stability issues found while building the actions system (2026-10-01)

Found while testing the first slice of `actions_and_keybindings.md`. None was investigated to a root cause: they were parked on purpose.
The smoke suite (`source/Editors/LevelEditor/smoke`) now runs the **Debug** build and ends with an "editor problem report"; an assert fails the run.

## Open issues

| # | Issue | What is known | Where to start |
|---|---|---|---|
| 1 | **Vulkan validation error `VUID-vkCmdDrawIndexed-None-08600`** ("pipeline created with layout A statically uses descriptor set 0, not compatible with the currently bound layout B"; "the set push constant ranges is different"). It also pops the red Error modal. | About 1,000 per full Debug suite run; also present in the old Debug build from before the actions work (99 in its run), so **not caused by it**. Silent at idle (0 errors after 8 s). Per test file on Release only `test_resource_editors.py` produced any (2). | Find the draw that binds one pipeline layout and draws with another pipeline: an ImGui or preview draw while a resource editor is open (Material/Texture/GeomStatic preview). The harness report prints the message and count. |
| 2 | **Intermittent access violation (0xc0000005)** while the harness opens the **Material** resource editor (`test_resource_editors.py::test_open_resource_editor[Material]`, the next command `list` finds the editor dead). | Seen in about 1 of 2-3 full runs, on Debug, and once on Release. Passes when that test runs alone, on both builds. Not yet checked on a build without the actions changes in a full run. | Run only `test_resource_editors.py` repeatedly; the SEH handler writes the stack to `LevelEditor.problems.log` next to the exe. May be related to #1 (the Material preview draws). |
| 3 | **An assert, hit once** in a Debug run (the user clicked Abort: "abort() has been called", exit code 3), during the `test_scenes_and_levels.py` stretch of a full run. | The text and stack were **lost**: the trace log is truncated at every launch. Not reproduced in 8 further Debug runs. | Asserts now go to `LevelEditor.problems.log` (append-only, with stack) and the harness exits instead of showing a dialog (`XEDITOR_NO_ASSERT_DIALOG`). If it recurs, the stack is in that file. |
| 4 | `Build/xLION.vs2022/LevelEditor.trace.log` is **1.1 GB**. The trace is never rotated or capped. | The Debug/Release copies are 6-12 MB. | Cap or rotate in `xeditor::diagnostics::Start`; find what writes it so verbosely. |
| 5 | `example.lionprj/Assets/imgui_level_editor.ini` is modified by every editor launch, including the smoke runs. | It is UI layout (per-user state living inside the project). | Same root as the open question in `actions_and_keybindings.md`: per-user state needs a per-user home. |

## Not done yet (actions / keybindings)

- The Keymap page in Project Settings, the command palette, F1 pin/overlay, the status line.
- Binding the inspector's `m_OnHelp` and a hint delegate on `toolbar.imgui` (so every tooltip comes from one system).
- Keys on enum values (Q/W/E/R are four actions for now), `member_icon`.
- Save/Undo/Redo still call functions directly, not `xeditor::Run` commands.
- Other editors' keys still hand-written: E10 files tab, Level tree F2/Delete, Texture (its Space overlaps the Drawer), Material graph, text widget, camera fly.
- The real keyboard path and the hover hint / menu look were only verified through `PressKeys` (shared resolver) and the build, not by hand in the UI.

## Housekeeping

- `actions.imgui` is committed locally on top of the official depot's first commit (`LIONant-depot/Actions.imgui`, LICENSE only) and
  fetched by `CMakeLists.txt` next to toolbar.imgui. **Not pushed yet** - `git push` from `dependencies/actions.imgui` publishes it; until then
  a fresh checkout would clone the empty depot.
- **Nothing is committed** in: xLION (this repo), `dependencies/xproperty`, `dependencies/xeditor`, `plugins/xlevel.plugin`.
  The four repos change together (xproperty: `member_dynamic_reason`, `m_OnHelp`, noexcept function members; xeditor: `host.h` drawer toggle,
  `diagnostics.h` problems log; xlevel.plugin: `session_actions`).
