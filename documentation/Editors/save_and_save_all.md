# Save and Save All

Two verbs, the same in every editor.

- **Save** saves the local work: what the person is looking at.
  - A resource editor saves its descriptor (`document_actions::Save`).
  - A Level editor saves the Level and the Scenes it may write (`xlevel::SaveEverything`). It does not write the renames and moves of the resource view: they are not the Level's work.
  - The resource view saves the renames, moves and new folders it keeps in memory (`xresource_editor::SaveAssets`, the `SaveAssets` command, its Save button).
- **Save All** makes sure everything in the editor is saved, whoever owns it. It is an event: `host.m_SaveAll.m_OnSave` (`xeditor/save_all.h`). Anything that keeps unsaved work subscribes and saves it when the event fires, and
  tells the `save_report` what it saved and what it could not. `xeditor::SaveAllNow()` fires it and toasts the failures. The application subscribes:
  1. the open resource editors (`open_resource_editors::SaveAll`), the Level editors among them;
  2. the resource database (`xresource_editor::SaveAssetsOnSaveAll`), after them.

  A subscriber that points at something shorter-lived than the host (a Level's editor) removes itself first (`RemoveDelegates`), the same rule as `host.m_IdleWork.m_OnRun`.

Where they are:

| | Save | Save All |
|---|---|---|
| Resource editors, Level editor | the floppy-disk button, `Ctrl+S`, the editor menu | the editor menu (the two-floppy icon), `Ctrl+Shift+S` |
| Resource view | the floppy-disk button at the left of the bar above the tree (enabled while something is waiting), the `SaveAssets` command | its menu (library icon and a down arrow, no Close) |
| Command line | `Save` (the Level's), `SaveAssets` (the resource view's) | `SaveAll` |

The icons are Segoe MDL2: `xeditor::save_icon_v` (U+E74E), `xeditor::save_all_icon_v` (U+EA35), `xeditor::menu_arrow_v` (U+E70D), `xeditor::library_icon_v` (U+E8F1).

Tests: `test_save_all.py`, `test_editor_menu.py`.
